"""DSL 解析 Mixin：将 LLM 输出的 JSON 转译为 Futu API 可执行的过滤条件"""

import asyncio
import json
from typing import Any, Dict, List

from pydantic import ValidationError

from backend.core.redis_client import redis_client
from backend.services.screener.models import ScreenerDecision


class DslParserMixin:
    """提供 DSL → Futu Filter 解析 + 技术形态二次过滤能力的 Mixin"""

    def parse_dsl_to_futu_filters(self, json_string: str):
        """将 Agent 的 JSON 转译为 Futu API 认识的 StockField 查询数组"""
        try:
            decision = ScreenerDecision.model_validate_json(json_string)
        except ValidationError as e:
            err_msgs = []
            # 💡 打印原始 Pydantic 错误详情到日志，方便调试
            print("❌ [Screener] Pydantic 验证失败详情:")
            for err in e.errors():
                print(f"   - 位置: {err['loc']}, 类型: {err['type']}, 消息: {err.get('msg', '')}")  # noqa: E501
                if "ctx" in err:
                    print(f"     上下文: {err['ctx']}")

            for err in e.errors():
                loc_list = list(err["loc"])
                human_loc = "->".join(map(str, loc_list))

                # 💡 将晦涩的 Pydantic 路径翻译为自然语言
                if len(loc_list) >= 3 and loc_list[0] == "filters":
                    idx = int(loc_list[1]) + 1
                    field_key = str(loc_list[2])
                    field_zh = {
                        "field": "筛选指标",
                        "type": "数据类型",
                        "term": "财报周期",
                        "min_value": "最小值",
                        "max_value": "最大值",
                    }.get(field_key, field_key)
                    human_loc = f"第 {idx} 个条件的「{field_zh}」"
                elif len(loc_list) == 1:
                    human_loc = {
                        "markets": "「交易市场」",
                        "exclude_st": "「剔除ST选项」",
                    }.get(str(loc_list[0]), str(loc_list[0]))

                err_msgs.append(f"{human_loc}类型或格式不匹配")

            raise ValueError(f"AI 生成的筛选条件越界: {', '.join(err_msgs)}。请尝试使用主流的量化财务指标。")  # noqa: E501
        except Exception as e:
            raise ValueError(f"大模型输出结构异常: {e}")

        futu_filters = []
        for f in decision.filters:
            # 💡 极简序列化：通过 by_alias 自动将 min_value 转为 min，并通过 exclude_none 剔除无用的空值  # noqa: E501
            cond = f.model_dump(by_alias=True, exclude_none=True)
            if cond.get("type") != "financial":
                cond.pop("term", None)

            # 💡 剔除附加给前端展示的中文名，防止污染发往富途底层的请求参数引发报错
            cond.pop("field_zh", None)

            # 💡 还原对底层 Futu 的真实字段名
            if cond.get("field") == "VOLUME_MULTIPLE":
                cond["field"] = "VOLUME_RATIO"

            futu_filters.append(cond)

        post_filters = {
            "exclude_st": decision.exclude_st,
            "technical_patterns": decision.technical_patterns or [],
        }

        return decision.markets, futu_filters, post_filters

    async def apply_technical_pattern_filtering(
        self, final_data: List[Dict[str, Any]], tech_patterns: List[str]
    ) -> List[Dict[str, Any]]:  # noqa: E501
        if not final_data:
            return final_data

        print(f"🔍 [Screener] 执行技术面二次流水线计算: {tech_patterns}，当前候选池 {len(final_data)} 只")  # noqa: E501
        from datetime import datetime, timezone

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        candidates = [r["symbol"] for r in final_data]

        # 1. 进阶优化：Redis Pipeline 极速批量查询缓存
        pipe = redis_client.pipeline()
        for sym in candidates:
            pipe.get(f"quant:tech:patterns:{sym}:{today_str}")
        cache_res = await pipe.execute()

        hit_patterns = {}
        hit_values = {}
        miss_symbols = []
        for sym, cached in zip(candidates, cache_res):
            if cached:
                parsed = json.loads(cached)
                # 兼容旧版的纯数组缓存结构
                if isinstance(parsed, dict):
                    hit_patterns[sym] = parsed.get("patterns", [])
                    hit_values[sym] = parsed.get("values", {})
                else:
                    hit_patterns[sym] = parsed
                    hit_values[sym] = {}
            else:
                miss_symbols.append(sym)

        # 💡 【核心防护】：彻底解决海量数据拉取导致的 API 额度耗尽与限流问题
        if miss_symbols:
            if not tech_patterns:
                # 场景 1：用户未指定形态过滤，纯粹只是为了 UI 附加标签。直接跳过拉取，仅展示已命中缓存的！  # noqa: E501
                print(f"⚡ [Screener] 当前未指定技术形态，主动跳过 {len(miss_symbols)} 只标的的 K 线拉取。")  # noqa: E501
            else:
                # 场景 2：直接拒绝拉取大量标的历史K线，防 API 熔断及额度榨干
                print(
                    f"⚠️ [Screener] 为防止 API 限流及消耗过多历史K线额度，取消实时批量拉取 {len(miss_symbols)} 只标的的历史K线数据。"
                )  # noqa: E501

        valid_tech_data = []

        PATTERN_ZH_MAP = {
            "macd_gold_cross": "MACD金叉",
            "rsi_oversold": "RSI超卖",
            "kdj_gold_cross": "KDJ金叉",
            "rsi_bottom_diverge": "RSI底背离",
            "rsi_top_diverge": "RSI顶背离",
            "macd_bottom_diverge": "MACD底背离",
            "macd_top_diverge": "MACD顶背离",
            "vcp_pattern": "VCP形态",
            "gap_up": "跳空高开",
            "volume_surge_3d": "连续三天放量",
            "insider_net_buy": "高管净买入",
        }

        # 剥离需要交给 Finnhub 等第三方服务的另类数据形态
        pure_tech_patterns = [p for p in tech_patterns if p != "insider_net_buy"]

        for r in final_data:
            sym = r["symbol"]
            # 将计算得到的技术指标值附加到结果字典中，前端检测到新 Key 会自动渲染为新列
            if sym in hit_values and hit_values[sym]:
                r.update(hit_values[sym])

            # 将命中的形态转换为中文标签并作为新列加入
            pats = hit_patterns.get(sym, [])
            if pats:
                r["matched_patterns"] = ", ".join([str(PATTERN_ZH_MAP.get(p, p)) for p in pats])  # noqa: E501

            # 💡 纯技术面放行逻辑
            if not pure_tech_patterns or all(p in pats for p in pure_tech_patterns):
                valid_tech_data.append(r)

        # ==========================================
        # 💡 另类数据 (Alternative Data) 联邦过滤
        # ==========================================
        if "insider_net_buy" in tech_patterns and valid_tech_data:
            print(f"🕵️‍♂️ [Screener] 执行另类数据过滤: 高管净买入，当前候选池 {len(valid_tech_data)} 只")  # noqa: E501
            from datetime import datetime, timedelta

            from backend.services.finnhub_service import finnhub_service

            async def _check_insider(row_data):
                try:
                    res = await finnhub_service.get_insider_transactions(row_data["symbol"], limit=30)  # noqa: E501
                    if res.get("status") == "success" and res.get("data"):
                        txs = res.get("data", [])
                        one_month_ago = datetime.now() - timedelta(days=30)
                        net_change = sum(
                            tx.get("change", 0)
                            for tx in txs
                            if tx.get("date") and datetime.strptime(tx.get("date"), "%Y-%m-%d") >= one_month_ago  # noqa: E501
                        )
                        if net_change > 0:
                            pats = row_data.get("matched_patterns", "")
                            row_data["matched_patterns"] = (pats + ", 高管净买入").strip(", ")  # noqa: E501
                            return row_data
                except Exception:
                    pass
                return None

            tasks = [_check_insider(r) for r in valid_tech_data]
            results = await asyncio.gather(*tasks)
            valid_tech_data = [r for r in results if r is not None]

        print(f"✅ [Screener] 技术形态流水线计算完成，最终剩余 {len(valid_tech_data)} 只")  # noqa: E501
        return valid_tech_data
