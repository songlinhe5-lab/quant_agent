import asyncio
import csv
import itertools
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import models
from backend.core.database import get_db
from backend.core.redis_client import redis_client
from backend.domain.strategy_parser import parse_strategy_parameters
from backend.routers.auth import get_current_user
from backend.services import strategy_version_service
from backend.services.ai_narrator.llm_service import llm_service

router = APIRouter(prefix="/strategy", tags=["Strategy Dev"])


class CodePayload(BaseModel):
    source_code: str


class GeneratePayload(BaseModel):
    prompt: str


class SaveStrategyPayload(BaseModel):
    source_code: str
    class_name: str
    message: Optional[str] = None  # STRAT-03a: 用户备注


class FormatPayload(BaseModel):
    source_code: str


_inspirations_cache: list[str] = []
_inspirations_lock = asyncio.Lock()


def RateLimiter(
    max_requests: int,
    window_seconds: int,
    global_max: Optional[int] = None,
    global_window: Optional[int] = None,
    by_user: bool = False,
):  # noqa: E501
    """细粒度 API 级别限流器与全局防刷双重风控依赖 (支持按 IP 或按 User ID)"""

    async def _execute_limit(request: Request, identifier: str):
        target_key = f"rate_limit_api:{request.url.path}:{identifier}"
        global_key = f"rate_limit_api_global:{request.url.path}"
        blacklist_key = f"rate_limit_blacklist:{identifier}"
        violation_key = f"rate_limit_violation:{identifier}"

        try:
            # 1. 🚨 优先检查是否在黑名单中，实现 O(1) 极速物理拦截
            is_banned = await redis_client.get(blacklist_key)
            if is_banned:
                raise HTTPException(
                    status_code=403,
                    detail="您的账号或 IP 因频繁恶意请求，已被系统自动封禁 24 小时。",
                )  # noqa: E501

            # 使用 Redis Pipeline 保证原子性并消除 N 次网络往返延迟 (RTT)
            async with redis_client.pipeline() as pipe:
                await pipe.incr(target_key)
                await pipe.expire(target_key, window_seconds, nx=True)

                if global_max:
                    await pipe.incr(global_key)
                    await pipe.expire(global_key, global_window or window_seconds, nx=True)  # noqa: E501

                results = await pipe.execute()

            if results[0] > max_requests:
                # 2. 🚨 记录违规次数 (触发 429 的次数)，违规记忆窗口设为 5 分钟
                async with redis_client.pipeline() as pipe:
                    await pipe.incr(violation_key)
                    await pipe.expire(violation_key, 300, nx=True)
                    v_results = await pipe.execute()

                # 3. 如果在 5 分钟内连续违规达到 5 次，正式关入小黑屋封禁 24 小时 (86400秒)  # noqa: E501
                if v_results[0] >= 5:
                    await redis_client.setex(blacklist_key, 86400, "1")
                    raise HTTPException(
                        status_code=403,
                        detail="检测到恶意高频攻击，已触发风控拦截，自动封禁 24 小时。",
                    )  # noqa: E501
                else:
                    raise HTTPException(
                        status_code=429,
                        detail=f"该接口请求过于频繁，当前限制为 {max_requests}次 / {window_seconds}秒。",
                    )  # noqa: E501

            if global_max and results[2] > global_max:
                raise HTTPException(
                    status_code=429,
                    detail="系统当前并发访问量过大，触发全局防刷保护，请稍后再试。",
                )  # noqa: E501
        except HTTPException:
            raise
        except Exception:
            pass  # 容灾：Redis 宕机时静默放行，不阻断业务

    if by_user:

        async def _rate_limit_user(request: Request, current_user: models.User = Depends(get_current_user)):  # noqa: E501
            # 基于用户 ID 进行限流 (FastAPI 会自动前置校验 JWT Token 并提取 user_id)
            await _execute_limit(request, f"user:{current_user.id}")

        return _rate_limit_user
    else:

        async def _rate_limit_ip(request: Request):
            # 基于客户端 IP 进行限流
            client_ip = request.client.host if request.client else "unknown"
            await _execute_limit(request, f"ip:{client_ip}")

        return _rate_limit_ip


async def _ensure_and_load_inspirations():
    global _inspirations_cache

    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "inspirations.csv"))  # noqa: E501

    async with _inspirations_lock:
        # 判断是否需要重建 (文件不存在 或 超过 24 小时未更新以吸纳最新热点)
        need_rebuild = False
        if not os.path.exists(csv_path):
            need_rebuild = True
        else:
            file_age = time.time() - os.path.getmtime(csv_path)
            if file_age > 86400:  # 24小时过期
                need_rebuild = True

        if need_rebuild:
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)

            # 💡 动态获取热点股票池 (从 Redis 全局自选/监控池读取)
            try:
                raw_assets = await redis_client.hkeys("quant:settings:monitored_refcounts")  # noqa: E501
                dynamic_assets = [t.decode("utf-8") if isinstance(t, bytes) else str(t) for t in raw_assets]  # noqa: E501
            except Exception:
                dynamic_assets = []

            # 兜底默认热门资产
            default_assets = [
                "AAPL",
                "TSLA",
                "NVDA",
                "MSFT",
                "00700.HK",
                "09988.HK",
                "BTC",
                "ETH",
                "SPY",
                "QQQ",
                "GLD",
                "USO",
                "TLT",
                "BABA",
                "PDD",
                "JD",
                "AMD",
                "INTC",
                "NFLX",
                "META",
            ]  # noqa: E501

            # 保证股票池深度：合并去重并截取前 30 个标的
            assets = list(dict.fromkeys(dynamic_assets + default_assets))[:30]

            indicators1 = ["MA5", "MA10", "MA20", "MA50", "EMA12", "EMA26", "SMA200"]
            indicators2 = ["MACD", "RSI", "KDJ", "BOLL", "ATR", "VWAP"]
            actions = [
                "交叉策略",
                "跌破买入",
                "超卖反弹",
                "均值回归",
                "趋势跟随",
                "放量突破",
                "顶背离做空",
                "底背离做多",
                "突破上轨",
            ]  # noqa: E501
            risk_controls = [
                "带 2.0 倍 ATR 动态止损",
                "固定 5% 止损",
                "触碰中轨平仓",
                "时间止损 5 天",
                "移动止盈 3%",
                "跌破短均线平仓",
                "利润回撤 20% 离场",
            ]  # noqa: E501

            try:
                # 放入线程池执行密集的文件生成与写入
                def _write_csv():
                    cache = []
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow(["prompt"])
                        combinations = itertools.product(assets, indicators1, indicators2, actions, risk_controls)  # noqa: E501
                        count = 0
                        for combo in combinations:
                            prompt = f"针对 {combo[0]} 的 {combo[1]} 与 {combo[2]} {combo[3]}，{combo[4]}"  # noqa: E501
                            writer.writerow([prompt])
                            cache.append(prompt)
                            count += 1
                            if count >= 20000:
                                break
                    return cache, count

                _inspirations_cache, count = await asyncio.to_thread(_write_csv)
                print(f"✅ [Strategy] 已根据最新热点股票池自动生成 {count} 条策略灵感到 {csv_path}")  # noqa: E501
            except Exception as e:
                print(f"⚠️ [Strategy] 生成 inspirations.csv 失败: {e}")

        # 如果缓存为空但文件已存在且未过期，从文件加载到内存
        if not _inspirations_cache and os.path.exists(csv_path):
            try:

                def _read_csv():
                    df = pd.read_csv(csv_path)
                    if "prompt" in df.columns:
                        return df["prompt"].dropna().tolist()
                    elif df.shape[1] > 0:
                        return df.iloc[:, 0].dropna().tolist()
                    return []

                _inspirations_cache = await asyncio.to_thread(_read_csv)
            except Exception as e:
                print(f"⚠️ [Strategy] 读取 inspirations.csv 失败: {e}")

    if not _inspirations_cache:
        _inspirations_cache = [
            "双均线(MA10, MA20)交叉策略，带 2.0 倍 ATR 动态止损",
            "RSI极度超卖(<20)且放量反弹策略，暴露阈值参数",
            "布林带均值回归：跌破下轨买入，触碰中轨平仓",
        ]
    return _inspirations_cache


# 💡 双重风控限流：单 IP 每 10 秒限 5 次；全网所有用户总和每 10 秒限 50 次 (防分布式代理群攻击)  # noqa: E501
@router.get(
    "/inspirations",
    dependencies=[
        Depends(RateLimiter(max_requests=5, window_seconds=10, global_max=50, global_window=10)),
        Depends(get_current_user),
    ],
)  # noqa: E501
async def get_inspirations(limit: int = 10):
    """随机获取策略研发灵感"""
    cache = await _ensure_and_load_inspirations()
    selected = random.sample(cache, min(limit, len(cache)))
    return {"status": "success", "data": selected}


@router.post("/parse-config", dependencies=[Depends(get_current_user)])
async def parse_strategy_config(payload: CodePayload):
    """接收在线编辑器的源码，解析并返回动态表单配置"""
    result = parse_strategy_parameters(payload.source_code)
    return result


@router.post("/generate")
async def generate_strategy_code(payload: GeneratePayload):
    """调用大模型一键生成策略代码"""
    prompt = f"""你是一个资深的量化交易架构师。请根据用户的自然语言描述，编写一个符合系统规范的 Python 量化策略类。

【开发规范】
1. 必须继承 `BaseStrategy`。注意：`BaseStrategy`, `np`, `pd`, `Literal` 均已在沙箱全局环境中注入。**严禁在代码中写 `import numpy` 或 `from xxx import BaseStrategy`**。
2. 必须包含 `__init__` 方法，并在其中定义可调参数，强制使用类型注解和默认值。对于下拉枚举参数，**必须使用 `Literal` 类型注解**（例如 `ma_type: Literal['SMA', 'EMA'] = 'SMA'`），系统将据此渲染下拉框。
3. 必须在类名下方或 `__init__` 内部编写标准的 Docstring 多行注释，通过 `:param 参数名: 中文描述` 为每个参数添加说明，以供前端解析渲染。
4. 🚀 **引擎规范 (VectorBT 极速矢量化)**：你现在是为 VectorBT 引擎提供信号，**必须彻底放弃事件驱动 (如 on_tick, on_bar)**，改用纯 Pandas 矢量化运算！
   - 必须实现 `_calculate_indicators(self)`：利用 pandas 原生运算计算特征列，**必须**计算出 `self.df['atr']` 用于引擎层的动态止损。
   - 必须实现 `_generate_signals(self)`：**绝对严禁进行任何资金或仓位管理 (如自建 self.position, self.cash)**！你只需专注于信号提取，通过矩阵逻辑位移 (`shift`) 直接生成 `self.df['signal']` 列。该列的值**只能**为 `1` (做多)，`-1` (做空)，`0` (平仓/观望)。
   - **绝对严禁**使用任何 `for` 循环、`df.iterrows()`、`df.apply(..., axis=1)` 或列表推导式遍历 K 线序列。条件判断必须且只能使用 Pandas 矢量化布尔掩码 (如 `&`, `|`) 或 `np.where`。
   - **绝对严禁**使用 Python 的 `and` / `or` 组合序列条件，必须使用 `&` / `|` 并且**强制用括号包裹每个子条件** (例如 `(df['A'] > 0) & (df['B'] < 0)`)，防止优先级报错。
   - **绝对严禁**使用链式赋值 (如 `df[mask]['signal'] = 1`)，必须使用 `df.loc[mask, 'signal'] = 1` 确保修改生效。
   - **绝对严禁**修改或覆盖原始的 `Open`, `High`, `Low`, `Close`, `Volume` 列的数据，引擎需要依赖它们进行准确的盈亏与滑点撮合。
   - **绝对严禁**定义跨 K 线的实例状态变量（如 `self.entry_price`, `self.days_held`, `self.is_bought` 等）。矢量化引擎在瞬间执行一次，使用此类变量将导致回测完全失效，所有状态必须表现为 df 的一列。
   - **绝对严禁**对 DataFrame 的列使用 `if df['A'] > df['B']:` 标量对比，必须防止 `The truth value of a Series is ambiguous` 报错。
   - **绝对严禁**使用 `shift(-n)` 等向后取值的函数引入未来数据 (Lookahead Bias)。
5. 必须且只能输出纯 Python 源码，严禁包含任何前言、后语或 ```python 标记。
6. 🚨 **环境限制**：严禁导入和使用 TA-Lib (talib)、VectorBT、Backtrader 等外部库！技术指标必须使用 pandas 的原生向量化方法在类内部自行实现。执行与图表渲染由沙箱环境外部自动接管。

用户策略需求：
{payload.prompt}
"""  # noqa: E501

    async def generate_stream():
        # 💡 立即下发 HTTP 200 OK 响应头与首个回车，彻底秒开前端代理的等待通道
        yield b"\n"

        try:
            # 💡 将大模型请求包装为异步 Task，使其在后台独立执行
            create_task = asyncio.create_task(
                llm_service.get_client().chat.completions.create(
                    model="deepseek-v4-pro",
                    temperature=0.2,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=120.0,
                    stream=True,
                    stream_options={"include_usage": True},
                )
            )

            # 💡 核心防断连：在等待大模型超长思考 (TTFB) 期间，每 0.5 秒下发一次换行符保活  # noqa: E501
            while not create_task.done():
                yield b"\n"
                await asyncio.sleep(0.5)

            resp = create_task.result()

            content = ""
            async for chunk in resp:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    # 💡 将思考过程组装为 NDJSON 格式流式下发，供给前端打字机渲染
                    yield (
                        json.dumps(
                            {"status": "reasoning", "data": reasoning},
                            ensure_ascii=False,
                        ).encode("utf-8")
                        + b"\n"
                    )  # noqa: E501

                content_val = delta.content
                if content_val:
                    content += content_val
                    # 💡 生成正式代码时同样持续下发换行符作为 Keep-Alive
                    yield b"\n"

            if content:
                content = content.strip()
                content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
                content = re.sub(r"\s*```$", "", content).strip()
                yield (json.dumps({"status": "success", "data": content}, ensure_ascii=False).encode("utf-8") + b"\n")  # noqa: E501
            else:
                yield (
                    json.dumps(
                        {"status": "error", "message": "大模型返回为空"},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    + b"\n"
                )  # noqa: E501
        except Exception as e:
            yield (json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False).encode("utf-8") + b"\n")  # noqa: E501

    return StreamingResponse(generate_stream(), media_type="application/x-ndjson")


@router.post("/format", dependencies=[Depends(get_current_user)])
async def format_strategy_code(payload: FormatPayload):
    """供 Monaco Editor 调用的独立 Black 代码格式化接口"""
    try:
        import black

        formatted_code = black.format_str(payload.source_code, mode=black.Mode())
        return {"status": "success", "data": formatted_code}
    except ImportError:
        return {"status": "error", "message": "未安装 black 模块"}
    except Exception as e:
        return {"status": "error", "message": f"格式化失败: {str(e)}"}


@router.post("/save", dependencies=[Depends(get_current_user)])
async def save_strategy(payload: SaveStrategyPayload, db: Session = Depends(get_db)):
    """保存策略源码到本地文件系统（草稿/工作区）+ 创建版本记录 (STRAT-03a)"""
    try:
        formatted_code = payload.source_code
        # 💡 尝试使用 Black 自动格式化 Python 代码
        try:
            import black

            # 使用 Black 默认的 PEP 8 风格规范排版
            formatted_code = black.format_str(payload.source_code, mode=black.Mode())
        except ImportError:
            print("⚠️ [Formatter] 未安装 black 模块，跳过自动格式化。您可以运行 pip install black 安装。")  # noqa: E501
        except Exception as e:
            # 如果代码存在未闭合的括号等严重语法错误，Black 会报错，此时降级使用原始代码保存  # noqa: E501
            print(f"⚠️ [Formatter] 代码存在语法异常，无法完成格式化: {e}")

        strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "drafts"))  # noqa: E501
        os.makedirs(strategies_dir, exist_ok=True)

        file_path = os.path.join(strategies_dir, f"{payload.class_name.lower()}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(formatted_code)

        # STRAT-03a: 创建版本记录
        version_result = strategy_version_service.save_version(
            db=db,
            strategy_name=payload.class_name,
            code=formatted_code,
            source="manual",
            message=payload.message,
        )

        return {
            "status": "success",
            "message": f"策略已成功保存至 {file_path}",
            "data": {
                "formatted_code": formatted_code,
                "version_id": version_result["version_id"],
                "seq": version_result["seq"],
                "code_hash": version_result["code_hash"][:8],
            },
        }  # noqa: E501
    except Exception as e:
        return {"status": "error", "message": f"保存失败: {str(e)}"}


@router.get("/list", dependencies=[Depends(get_current_user)])
async def list_strategies():
    """拉取已保存的策略草稿列表"""
    strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "drafts"))  # noqa: E501
    if not os.path.exists(strategies_dir):
        return {"status": "success", "data": []}

    results = []
    for file_name in os.listdir(strategies_dir):
        if file_name.endswith(".py"):
            file_path = os.path.join(strategies_dir, file_name)
            stat = os.stat(file_path)
            modified_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")  # noqa: E501
            results.append(
                {
                    "name": file_name[:-3],  # 移除 .py 后缀
                    "lang": "Python",
                    "version": "Draft",
                    "status": "testing",
                    "modified": modified_time,
                }
            )
    results.sort(key=lambda x: x["modified"], reverse=True)
    return {"status": "success", "data": results}


# ─────────────────────────────────────────────────────────────
# STRAT-03a: 策略版本管理端点
# ─────────────────────────────────────────────────────────────


@router.get("/{name}/versions", dependencies=[Depends(get_current_user)])
async def get_strategy_versions(name: str, limit: int = 50, db: Session = Depends(get_db)):
    """获取策略版本时间线 (STRAT-03a)"""
    versions = strategy_version_service.get_versions(db, name, limit=limit)
    return {"status": "success", "data": versions}


@router.get("/versions/{version_id}", dependencies=[Depends(get_current_user)])
async def get_strategy_version(version_id: str, db: Session = Depends(get_db)):
    """获取单个版本的完整信息（含代码）(STRAT-03a)"""
    version = strategy_version_service.get_version(db, version_id)
    if not version:
        return {"status": "error", "message": f"版本 {version_id} 不存在"}
    return {"status": "success", "data": version}


@router.post("/{name}/restore", dependencies=[Depends(get_current_user)])
async def restore_strategy_version(name: str, payload: dict, db: Session = Depends(get_db)):
    """恢复指定版本，创建新的 restore 版本 (STRAT-03a)"""
    version_id = payload.get("version_id")
    if not version_id:
        return {"status": "error", "message": "缺少 version_id 参数"}

    result = strategy_version_service.restore_version(db, name, version_id)
    if not result:
        return {"status": "error", "message": f"源版本 {version_id} 不存在"}

    return {
        "status": "success",
        "message": f"已恢复至版本 {version_id[:8]}",
        "data": result,
    }


@router.get("/draft/{name}", dependencies=[Depends(get_current_user)])
async def get_draft_strategy(name: str):
    """拉取指定策略的完整源码"""
    strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "drafts"))  # noqa: E501
    file_path = os.path.join(strategies_dir, f"{name}.py")
    if not os.path.exists(file_path):
        return {"status": "error", "message": "策略文件不存在"}

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    return {"status": "success", "data": {"source_code": source_code}}


@router.delete("/draft/{name}", dependencies=[Depends(get_current_user)])
async def delete_draft_strategy(name: str):
    """彻底删除指定的策略草稿"""
    strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "drafts"))  # noqa: E501
    file_path = os.path.join(strategies_dir, f"{name}.py")
    if not os.path.exists(file_path):
        return {"status": "error", "message": "策略文件不存在"}
    try:
        os.remove(file_path)
        return {"status": "success", "message": f"策略 {name} 已被删除"}
    except Exception as e:
        return {"status": "error", "message": f"删除失败: {str(e)}"}
