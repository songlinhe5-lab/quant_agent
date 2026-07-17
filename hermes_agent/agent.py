import asyncio
import functools
import json
import os
import re
from typing import Any, Dict, List, Optional, cast

import redis.asyncio as redis
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError, field_validator
from rich.console import Console
from rich.markdown import Markdown

from backend.core.utils import safe_truncate


class SessionTitleValidator(BaseModel):
    """Pydantic 模型：用于校验和清洗大模型生成的会话标题"""

    title: str

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        # 1. 违禁词库拦截 (可扩展为从 Redis 动态读取)
        banned_words = ["测试违禁", "色情", "暴力", "政治敏感"]
        if any(banned in v for banned in banned_words):
            raise ValueError("触发敏感词风控拦截")

        # 2. 乱码清洗：仅保留中文、英文字母、数字和基础空格/横线，过滤非法语义字符
        cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s\-]", "", v)
        if not cleaned.strip():
            raise ValueError("标题清洗后为空(疑似大模型产生纯乱码幻觉)")

        # 3. 长度硬限制拦截
        return cleaned[:15].strip()


def with_reference_check(max_retries: int = 2):
    """
    Agent 专属输出自愈装饰器。
    校验大模型返回的最终内容中，正文引用的 [X] 是否都在文末的参考文献列表中。
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                result = await func(self, *args, **kwargs)
                if not isinstance(result, str):
                    return result

                # 💡 如果是自愈轮次（判断 self.messages[-2] 是否为拦截提示），跳过后续校验直接返回
                is_correction = len(self.messages) >= 2 and "系统校验拦截" in str(self.messages[-2].get("content", ""))
                if is_correction:
                    return result

                # 💡 使用正则兼容大模型花式的 Markdown 标题和冒号
                parts = re.split(r"📚\s*(?:\*\*|\*)?参考文献(?:\*\*|\*)?[:：]?", result)
                if len(parts) > 1:
                    main_text = parts[0]
                    ref_text = parts[-1]
                else:
                    main_text = result
                    ref_text = ""

                # 提取正文和参考列表中的引用序号
                citations = set(re.findall(r"\[(\d+)\]", main_text))
                references = set(re.findall(r"\[(\d+)\]", ref_text))

                missing = citations - references
                if missing and attempt < max_retries - 1:
                    self.console.print(
                        f"\n[bold yellow]⚠️ [Auto-Correction] 检测到正文引用了 {missing} 但未列出参考文献，触发大模型自愈 (第 {attempt + 1} 次)...[/bold yellow]"
                    )

                    # 注入纠错提示
                    self.messages.append(
                        {
                            "role": "user",
                            "content": f"⚠️ 系统校验拦截：你在刚才的回答正文中使用了引用标号 {', '.join([f'[{m}]' for m in missing])}，但在文末并没有提供对应的「📚 参考文献」列表，或者列表中遗漏了这些序号。请补充完整的参考文献列表并重新输出完整的回答。",
                        }
                    )
                    await self._save_session()
                    continue  # 拦截本次返回，重新进入循环让 LLM 再生成一次

                return result

        return wrapper

    return decorator


class HermesAgent:
    """
    Hermes Agent 核心主脑类
    职责：维护上下文状态、对接大模型 API、调度 ReAct 工作流。
    """

    def __init__(
        self,
        tool_registry,
        system_prompt_path: str,
        session_id: str = "default",
        llm_client: Optional[AsyncOpenAI] = None,
        redis_client: Optional[redis.Redis] = None,
    ):
        self.console = Console()
        self.tool_registry = tool_registry
        self.system_prompt_path = system_prompt_path
        self.session_id = session_id
        self.memory_key = f"hermes:memory:{self.session_id}"

        # 💡 初始化同步 Redis 客户端 (极低延迟，可直接替换原有文件 I/O)
        if redis_client:
            self.redis_client = redis_client
        else:
            self.redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                password=os.getenv("REDIS_PASSWORD") or "quant_redis_secret_2026",
                decode_responses=True,
            )

        # 💡 是否开启 Debug 模式
        self.debug_mode = os.getenv("QUANT_ENV") == "development"

        # 💡 初始化 DeepSeek 客户端 (复用 OpenAI SDK)
        if llm_client:
            self.client = llm_client
        else:
            api_key = os.getenv("LLM_API_KEY")
            if not api_key:
                print("⚠️ 警告: 未找到 LLM_API_KEY 环境变量，请在 .env 中配置。")
            api_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
            self.client = AsyncOpenAI(api_key=api_key, base_url=api_base_url)
        self.model = os.getenv("LLM_MODEL", "deepseek-v4-flash")
        self.pro_model = os.getenv("LLM_PRO_MODEL", "deepseek-v4-pro")
        self.vision_model = os.getenv("LLM_VISION_MODEL", "deepseek-v4-pro")  # 保留配置，但暂时禁用

        # 1. 加载系统指令 (AGENTS.md)
        self.system_prompt = self._load_system_prompt()

        # 2. 初始化对话记忆 (Context Window)
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]

        print(f"🧠 [Agent Brain] 初始化完成。主推理: {self.model} | 深度分析: {self.pro_model}")

    async def initialize(self):
        """异步初始化：从 Redis 加载历史记忆"""
        await self._load_session()

    def _apply_system_prompt(self, messages: list):
        """辅助方法：强制使用最新版本的系统指令覆盖历史记忆"""
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = self.system_prompt
        else:
            messages.insert(0, {"role": "system", "content": self.system_prompt})

    async def _load_session(self):
        """从 Redis 加载历史记录。若未命中，尝试从 PostgreSQL 唤醒冷数据"""
        try:
            raw_data = await self.redis_client.get(self.memory_key)
            if raw_data:
                saved_messages = json.loads(raw_data)
                self._apply_system_prompt(saved_messages)
                self.messages = saved_messages
                print(f"📦 [Memory] 成功从 Redis 加载历史对话，共恢复 {len(self.messages) - 1} 条记录。")
                return
        except Exception as e:
            print(f"⚠️ [Memory] 从 Redis 读取历史失败: {e}")

        # 💡 冷热分离：Redis 中没找到（可能已过期或因重启丢失），去 PostgreSQL 数据库捞取
        try:

            def fetch_db():
                # 延迟内部导入以避免独立启动 Agent 时的模块循环依赖
                from backend.core.database import SessionLocal
                from backend.core.models import AgentSession

                with SessionLocal() as db:
                    record = db.query(AgentSession).filter(AgentSession.session_id == self.session_id).first()
                    if record and record.messages:
                        return record.messages
                return None

            db_messages = await asyncio.to_thread(fetch_db)
            if db_messages:
                self._apply_system_prompt(db_messages)
                self.messages = db_messages
                print(f"🗄️ [Memory] 成功从 PostgreSQL 唤醒冷数据对话，共恢复 {len(self.messages) - 1} 条记录。")
                # 重新将捞取的冷数据写入 Redis 激活为热缓存
                await self._save_session()
                return
        except Exception as e:
            print(f"⚠️ [Memory] 从 PostgreSQL 唤醒冷数据失败: {e}")

        # 如果完全没有历史，则初始化全新记忆
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def _heal_memory(self):
        """修复因为异常中断导致的孤立 tool_calls 破坏上下文记录的问题"""
        healed = []
        for m in self.messages:
            # 如果上一条是没闭环的 tool_calls，且当前这条不是 tool 的回执，则剔除破损的上一条
            if healed and healed[-1].get("role") == "assistant" and healed[-1].get("tool_calls"):
                if m.get("role") != "tool":
                    healed.pop()
            healed.append(m)

        if healed and healed[-1].get("role") == "assistant" and healed[-1].get("tool_calls"):
            self.console.print("[dim red]🐛 [Memory] 检测到末尾残留未闭环的 tool_calls，已剔除。[/dim red]")
            healed.pop()

        if len(healed) != len(self.messages):
            self.console.print(
                "\n[dim yellow]🩹 [Memory] 检测到破损的工具调用上下文，已自动完成记忆修复！[/dim yellow]"
            )
            self.messages = healed

        self._compress_memory()

    def _compress_memory(self, max_messages: int = 30, max_tool_len: int = 800):
        """上下文记忆智能压缩机制：防止历史记录过长导致 Token 溢出与性能下降"""
        if len(self.messages) <= 2:
            return

        # 1. 有损压缩：截断非最新轮次的巨型 Tool 返回值 (如过去的 K 线或财务报表)
        # 逻辑：模型得出当前轮结论后，旧的原始行情对未来的上下文价值极低，直接折叠。
        for i in range(1, len(self.messages) - 4):  # 避开最新的 4 条记录，保证当轮推理完整
            msg = self.messages[i]
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                if len(msg["content"]) > max_tool_len:
                    # 💡 采用自适应截断，防止将 JSON 或 Markdown 从中间生硬劈断导致解析异常
                    msg["content"] = safe_truncate(
                        msg["content"],
                        max_tool_len,
                        suffix="\n... [老旧数据已被系统折叠，省略 {omitted} 字符以释放内存] ...",
                    )

        # 2. 滑动窗口：如果消息数依然超过最大阈值，安全剥离最老的记录
        if len(self.messages) > max_messages:
            self.console.print(
                f"[dim yellow]🗜️ [Memory] 上下文达 {len(self.messages)} 条，触发滑动窗口自动瘦身...[/dim yellow]"
            )
            system_msg = [self.messages[0]]  # 永远保留系统的 System Prompt

            cut_idx = len(self.messages) - max_messages
            # 🚨 安全锁：寻找安全的切分点，绝不能从孤立的 tool 消息或者断裂的 tool_calls 中间切开
            # 如果切分点刚好是一个 tool 结果，往后顺延，直到找到一个完整的 user 提问或 assistant 普通对话
            while cut_idx < len(self.messages) and self.messages[cut_idx].get("role") in ["tool", "assistant"]:
                cut_idx += 1

            self.messages = system_msg + self.messages[cut_idx:]

    async def _save_session(self):
        """将会话历史保存到 Redis (热数据)，并抛出后台任务异步落库 PostgreSQL (冷数据)"""
        try:
            # 1. 存入 Redis，TTL 设为 43200 秒 (12小时)
            await self.redis_client.set(self.memory_key, json.dumps(self.messages, ensure_ascii=False), ex=43200)

            # 2. 💡 触发异步落盘任务，不阻塞当前的事件循环与大模型流式输出
            # 传入浅拷贝 list() 防止在异步落盘期间消息数组在主线程中被修改
            asyncio.create_task(self._async_db_upsert(self.session_id, list(self.messages)))

        except Exception as e:
            print(f"⚠️ [Memory] 记忆保存失败: {e}")

    async def _async_db_upsert(self, session_id: str, messages: list):
        """后台守护任务：将历史记忆异步 Upsert 到 PostgreSQL"""
        try:
            # 1. 检查是否为新会话，或是否需要由大模型生成精简标题
            def check_needs_title():
                from backend.core.database import SessionLocal
                from backend.core.models import AgentSession

                with SessionLocal() as db:
                    record = db.query(AgentSession).filter(AgentSession.session_id == session_id).first()
                    return record is None or record.title == "新对话"

            needs_title = await asyncio.to_thread(check_needs_title)

            new_title = "新对话"
            if needs_title:
                # 提取用户第一句话
                user_content = ""
                for m in messages:
                    if m.get("role") == "user":
                        c = m.get("content")
                        if isinstance(c, str):
                            user_content = c.strip()
                        elif isinstance(c, list):  # 兼容多模态的 content 数组
                            user_content = next(
                                (item.get("text", "") for item in c if item.get("type") == "text"), ""
                            ).strip()
                        if user_content:
                            break

                if user_content:
                    try:
                        # 调用大模型生成 3 个词的专业短标题
                        response = await self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "你是一个标题生成器。请用极简、专业的中文（不超过3个词或10个汉字）精准总结用户的提问作为标题。严禁输出任何标点符号、引号或其他解释性文字。",
                                },
                                {"role": "user", "content": user_content},
                            ],
                            temperature=0.3,
                            max_tokens=15,
                        )
                        raw_title = response.choices[0].message.content
                        new_title = raw_title.strip("。，. \"'“”") if raw_title else user_content[:20]

                        # 🛡️ Pydantic 安全清洗与格式校验
                        validated = SessionTitleValidator(title=new_title)
                        new_title = validated.title

                        print(f"🧠 [Agent Memory] 智能标题已生成: {new_title}")
                    except ValidationError as ve:
                        print(f"⚠️ [Agent Memory] 标题校验未通过 ({ve.errors()[0]['msg']})，降级为文本截断")
                        new_title = user_content[:20] + ("..." if len(user_content) > 20 else "")
                    except Exception as e:
                        print(f"⚠️ [Agent Memory] 智能标题生成失败，降级为文本截断: {e}")
                        new_title = user_content[:20] + ("..." if len(user_content) > 20 else "")

            # 2. 实际执行数据库更新
            def db_op():
                from backend.core.database import SessionLocal
                from backend.core.models import AgentSession

                with SessionLocal() as db:
                    record = db.query(AgentSession).filter(AgentSession.session_id == session_id).first()
                    if record:
                        record.messages = messages
                        if needs_title and new_title != "新对话":
                            record.title = new_title
                    else:
                        new_record = AgentSession(session_id=session_id, title=new_title, messages=messages)
                        db.add(new_record)
                    db.commit()

            # 使用线程池抛出同步的 SQLAlchemy ORM 事务
            await asyncio.to_thread(db_op)
        except Exception as e:
            print(f"⚠️ [DB Error] 异步落库 PostgreSQL 失败: {e}")

    def _load_system_prompt(self) -> str:
        """读取量化系统的红线与工作流设定"""
        base_prompt = "你是一个专业的量化交易 Agent。"
        if os.path.exists(self.system_prompt_path):
            with open(self.system_prompt_path, "r", encoding="utf-8") as f:
                base_prompt = f.read()
        else:
            print(f"⚠️ 警告: 未找到系统指令文件 {self.system_prompt_path}")

        # 💡 动态注入防幻觉指令：禁止大模型在生成代码时调用工具去拉取数据，避免浪费时间与 Token
        code_gen_rule = "\n\n⚠️ 【严格风控指令】当用户要求你“编写”、“生成”量化策略代码或因子特征提取代码时，请**直接输出纯 Python 代码**，绝对不允许调用 `get_broker_market_data` 等工具去拉取 K 线或行情数据来进行测试验证。真实的行情数据拉取与回测将在独立的沙箱工作台中自动完成。"

        return base_prompt + code_gen_rule

    async def run_cli(self):
        """
        启动交互终端
        """
        self.console.print("\n[bold green]🟢 [Terminal] 量化网关 CLI 启动。输入 'exit' 退出。[/bold green]")
        while True:
            try:
                user_input = self.console.input("\n[bold cyan][Trader] 👤:[/bold cyan] ").strip()
                if user_input.lower() in ["exit", "quit"]:
                    break

                # 新增快捷指令：一键清空历史记忆，防止旧报错导致大模型产生幻觉
                if user_input.lower() == "/clear":
                    self.messages = [{"role": "system", "content": self.system_prompt}]
                    await self._save_session()
                    self.console.print("\n[bold yellow]🧹 [Memory] 历史记忆已彻底清空，大脑已重置！[/bold yellow]")
                    continue

                if not user_input:
                    continue

                # 在加入新指令前，强制运行上下文体检自愈
                self._heal_memory()
                # 将用户输入加入上下文
                self.messages.append({"role": "user", "content": user_input})
                await self._save_session()

                # 触发大模型思考与工具调用循环
                await self._step_loop()

            except KeyboardInterrupt:
                print("\n\n[System] 收到强制中断信号，正在安全关闭...")
                break
            except Exception as e:
                print(f"\n❌ [System Fatal] 核心循环异常: {e}")

    async def chat(self, user_input: str = "", attachments: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        异步单轮对话接口，专门提供给 FastAPI / WebSocket 等外部程序调用。
        """
        # 新增快捷指令：一键清空历史记忆
        if user_input.strip().lower() == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            await self._save_session()
            return "🧹 历史记忆已彻底清空，大脑已重置！"

        self._heal_memory()

        # 💡 多模态支持：如果携带了图片等附件，采用 OpenAI 兼容的视觉/多模态消息数组格式
        if user_input.strip() or attachments:
            # 暂时禁用图片识别：attachments 不再作为消息内容的一部分发送给 LLM
            # 只发送文本内容
            if user_input.strip():
                self.messages.append({"role": "user", "content": user_input.strip()})
        await self._save_session()

        if len(self.messages) <= 1:
            return ""

        try:
            result = await self._step_loop()
            return result if result else "⚠️ 思考完成，但未返回任何内容。"
        except Exception as e:
            return f"❌ [Agent Runtime Error] 运行异常: {e}"

    @with_reference_check(max_retries=2)
    async def _step_loop(self):
        """
        核心 ReAct 执行循环 (Plan -> Tool -> Verify -> Output)
        """
        max_iterations = 8
        for i in range(max_iterations):
            print(f"🤖 [Agent] 思考中 (第 {i + 1} 轮)...")
            try:
                # 💡 动态模型切换：如果最新一条用户消息包含图片，自动切换至多模态视觉模型
                model_to_use = self.model  # 暂时禁用视觉模型，强制使用文本模型

                schemas = self.tool_registry.get_all_schemas()
                request_kwargs = {
                    "model": model_to_use,
                    "messages": cast(Any, self.messages),
                    "temperature": 0.0,  # 量化场景要求低随机性，确保结果确定性
                }
                if schemas:
                    request_kwargs["tools"] = schemas

                if self.debug_mode:
                    self.console.print("\n[dim cyan]--- 🐛 [Debug] LLM Request ---[/dim cyan]")
                    # 使用 default=str 防止遇到无法序列化的特殊对象导致崩溃
                    self.console.print(
                        f"[dim]Messages: {json.dumps(request_kwargs['messages'], ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    if "tools" in request_kwargs:
                        self.console.print(f"[dim]Tools Configured: {len(request_kwargs['tools'])}[/dim]")
                    self.console.print("[dim cyan]------------------------------[/dim cyan]\n")

                response = await self.client.chat.completions.create(**request_kwargs)
                msg = response.choices[0].message

                if self.debug_mode:
                    self.console.print("\n[dim magenta]--- 🐛 [Debug] LLM Response ---[/dim magenta]")
                    self.console.print(
                        f"[dim]{json.dumps(msg.model_dump(exclude_none=True), ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    self.console.print("[dim magenta]-------------------------------[/dim magenta]\n")

                # 将模型回复加入上下文 (使用 exclude_none 防止结构冗余)
                self.messages.append(msg.model_dump(exclude_none=True))
                # ❌ 移除这里的 self._save_session()，防止中途崩溃导致上下文未闭环就被写入硬盘

                # 如果模型决定调用工具
                if msg.tool_calls:

                    async def safe_execute(tc):
                        print(f"🧠 [Agent Plan] 决定调用工具: {tc.function.name}")
                        try:
                            args = json.loads(tc.function.arguments)
                            # 💡 核心修复：execute 是 async 函数，必须 await
                            return await self.tool_registry.execute(tc.function.name, **args)
                        except Exception as e:
                            return {"status": "error", "message": f"工具执行异常: {str(e)}"}

                    tasks = [safe_execute(tc) for tc in msg.tool_calls]
                    # 并发执行所有工具，并捕获底层的崩溃防止跳过组装步骤
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for tool_call, result in zip(msg.tool_calls, results):
                        if isinstance(result, Exception):
                            result = {"status": "error", "message": f"并发调度异常: {str(result)}"}
                        # 将工具执行结果作为 tool role 加入上下文
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                    await self._save_session()  # ✅ 工具结果全部安全追加完毕后，再进行本地保存
                    # 继续下一轮循环，让模型根据工具结果进行 Verify 和 Output
                else:
                    await self._save_session()  # ✅ 如果不需要调用工具，则证明推理完整结束，直接保存
                    # 模型没有调用工具的需求，得出最终结论 (Output)
                    self.console.print("\n[bold green]💬 [Agent Output]:[/bold green]")
                    self.console.print(Markdown(msg.content or ""))  # 加入 or "" 防止模型未输出内容导致 Rich 渲染报错
                    return msg.content or ""

            except Exception as e:
                print(f"❌ [Agent API Error] 大模型交互异常: {e}")
                return f"❌ 大模型交互异常: {e}"

        print("⚠️ [Agent Warning] 达到最大思考循环次数，启动强制熔断恢复策略。")
        try:
            # 强制恢复：向模型注入提示，要求其根据现有上下文强制输出结论
            self.messages.append(
                {
                    "role": "user",
                    "content": "⚠️ 系统强制指令：你的思考与工具调用次数已达上限。请立即停止尝试使用工具，仅根据当前上下文中已获取到的数据，给出一个最终的分析总结。",
                }
            )

            # 进行最后一次无 Tools 的 API 请求，强制剥夺模型的工具使用权
            # 💡 使用 pro 模型进行深度分析总结，提升最终结论质量
            response = await self.client.chat.completions.create(
                model=self.pro_model, messages=cast(Any, self.messages), temperature=0.0
            )
            final_msg = response.choices[0].message
            self.messages.append(final_msg.model_dump(exclude_none=True))
            await self._save_session()

            self.console.print("\n[bold yellow]💬 [Agent Output (强制总结)]:[/bold yellow]")
            self.console.print(Markdown(final_msg.content or ""))
            return final_msg.content or ""
        except Exception as e:
            print(f"❌ [Agent API Error] 强制恢复失败: {e}")
            return f"❌ 强制恢复失败: {e}"

    async def chat_stream_async(self, user_input: str = "", attachments: Optional[List[Dict[str, Any]]] = None):
        """
        异步流式对话接口 (供 FastAPI 与支持异步的 CLI 终端调用)
        """
        if user_input.strip().lower() == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            await self._save_session()
            yield {"type": "text_chunk", "content": "🧹 历史记忆已彻底清空，大脑已重置！"}
            return

        self._heal_memory()

        # 💡 多模态支持：将 base64 附件拼装为支持视觉大模型的数组结构
        if user_input.strip() or attachments:
            # 暂时禁用图片识别：attachments 不再作为消息内容的一部分发送给 LLM
            # 只发送文本内容
            if user_input.strip():
                self.messages.append({"role": "user", "content": user_input.strip()})
        await self._save_session()

        if len(self.messages) <= 1:
            self.console.print("⚠️ [Agent Stream] 上下文为空 (或仅含 System 指令)，拒绝发起大模型请求。")
            return  # 仅有 system prompt 时不触发大模型请求

        max_iterations = 8
        for i in range(max_iterations):
            # 💡 每轮 ReAct 开始前发送心跳，防止工具完成后到下一轮 LLM 响应前的空白期被 Cloudflare 掐断
            yield {"type": "heartbeat", "tick": i + 1}
            self.console.print(f"🤖 [Agent Stream] 流式思考中 (第 {i + 1} 轮)...")
            try:
                # 💡 动态模型切换：如果最新一条用户消息包含图片，自动切换至多模态视觉模型
                model_to_use = self.model  # 暂时禁用视觉模型，强制使用文本模型

                schemas = self.tool_registry.get_all_schemas()
                request_kwargs = {
                    "model": model_to_use,
                    "messages": cast(Any, self.messages),
                    "temperature": 0.0,
                    "stream": True,  # 开启大模型的流式输出开关
                }
                if schemas:
                    request_kwargs["tools"] = schemas

                if self.debug_mode:
                    self.console.print("\n[dim cyan]--- 🐛 [Debug Stream] LLM Request Payload ---[/dim cyan]")
                    self.console.print(
                        f"[dim]{json.dumps(request_kwargs['messages'], ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    self.console.print("[dim cyan]----------------------------------------------[/dim cyan]\n")

                self.console.print("🌐 [Chat API] 正在向大模型发起流式请求 (等待首个 Token)...")
                response = await self.client.chat.completions.create(**request_kwargs)
                self.console.print("✅ [Chat API] 已接收到大模型流式响应，开始处理数据流...")

                collected_content = ""
                tool_calls_dict = {}
                chunk_count = 0

                async for chunk in response:
                    chunk_count += 1
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # 💡 兼容 DeepSeek 等带有 CoT (Chain of Thought) 模型的深度思考流
                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if reasoning_content:
                        yield {"type": "reasoning_chunk", "content": reasoning_content}

                    content_val = delta.content
                    if content_val:
                        collected_content += content_val
                        # 向终端/前端抛出普通文本的流式切片
                        yield {"type": "text_chunk", "content": content_val}

                    if delta.tool_calls:
                        # 手动拼接流式的 Tool Call 碎片数据
                        for tc_chunk in delta.tool_calls:
                            idx = tc_chunk.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc_chunk.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc_chunk.function.name or "",
                                        "arguments": tc_chunk.function.arguments or "",
                                    },
                                }
                            else:
                                if tc_chunk.function.name:
                                    tool_calls_dict[idx]["function"]["name"] += tc_chunk.function.name
                                if tc_chunk.function.arguments:
                                    tool_calls_dict[idx]["function"]["arguments"] += tc_chunk.function.arguments

                msg_dict = {"role": "assistant", "content": collected_content if collected_content else None}
                if tool_calls_dict:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                        }
                        for idx, tc in sorted(tool_calls_dict.items())
                    ]

                self.console.print(f"✅ [Chat API] 本轮流式接收完毕，共解析 {chunk_count} 个 Chunk。")

                if self.debug_mode:
                    self.console.print("\n[dim magenta]--- 🐛 [Debug Stream] LLM Response Assembled ---[/dim magenta]")
                    self.console.print(f"[dim]{json.dumps(msg_dict, ensure_ascii=False, indent=2, default=str)}[/dim]")
                    self.console.print("[dim magenta]------------------------------------------------[/dim magenta]\n")

                self.messages.append({k: v for k, v in msg_dict.items() if v is not None})

                if tool_calls_dict:
                    for tc in msg_dict["tool_calls"]:
                        yield {
                            "type": "tool_start",
                            "name": tc["function"]["name"],
                            "input": tc["function"]["arguments"],
                        }

                    async def safe_execute(tc):
                        try:
                            # 💡 核心修复：execute 是 async 函数，必须 await
                            return await self.tool_registry.execute(
                                tc["function"]["name"], **json.loads(tc["function"]["arguments"])
                            )
                        except Exception as e:
                            return {"status": "error", "message": f"工具执行异常: {str(e)}"}

                    # 💡 心跳保活：工具执行期间定期发送 heartbeat，防止 Cloudflare 100s 空闲超时掐断连接
                    result_queue: asyncio.Queue = asyncio.Queue()

                    async def run_and_queue(tc):
                        res = await safe_execute(tc)
                        await result_queue.put((tc, res))

                    tool_tasks = [asyncio.create_task(run_and_queue(tc)) for tc in msg_dict["tool_calls"]]
                    heartbeat_count = 0

                    while tool_tasks:
                        try:
                            tc, res = await asyncio.wait_for(result_queue.get(), timeout=15.0)
                        except asyncio.TimeoutError:
                            # 发送心跳保活，防止 Cloudflare/Nginx 空闲断连
                            heartbeat_count += 1
                            yield {"type": "heartbeat", "tick": heartbeat_count}
                            continue

                        final_res = {"status": "error", "message": str(res)} if isinstance(res, Exception) else res
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": tc["function"]["name"],
                                "content": json.dumps(final_res, ensure_ascii=False),
                            }
                        )
                        # 抛出执行结果给前端或 CLI 终端展示
                        yield {"type": "tool_result", "name": tc["function"]["name"], "result": final_res}
                        tool_tasks = [t for t in tool_tasks if not t.done()]

                    await self._save_session()
                else:
                    # 💡 流式输出时的自愈拦截
                    if collected_content:
                        # 💡 如果是系统自愈的补充回复，不需要再做文献完整性检查
                        is_correction_turn = len(self.messages) >= 2 and "系统校验拦截" in str(
                            self.messages[-2].get("content", "")
                        )
                        if not is_correction_turn:
                            # 💡 兼容大模型任意加粗格式的标题
                            parts = re.split(r"📚\s*(?:\*\*|\*)?参考文献(?:\*\*|\*)?[:：]?", collected_content)
                            if len(parts) > 1:
                                main_text = parts[0]
                                ref_text = parts[-1]
                            else:
                                main_text = collected_content
                                ref_text = ""

                            citations = set(re.findall(r"\[(\d+)\]", main_text))
                            references = set(re.findall(r"\[(\d+)\]", ref_text))
                            missing = citations - references

                            if missing and i < max_iterations - 1:
                                self.console.print(
                                    f"\n[bold yellow]⚠️ [Stream Auto-Correction] 检测到遗漏参考文献 {missing}，触发流式自愈补充...[/bold yellow]"
                                )

                                # 向前端追加自愈提示的 UI 渲染
                                yield {
                                    "type": "text_chunk",
                                    "content": f"\n\n> 🔄 *系统自检：正在自动补充遗漏的参考文献 {missing}...*\n\n",
                                }

                                # 注入纠错提示，要求大模型仅输出补充内容
                                self.messages.append(
                                    {
                                        "role": "user",
                                        "content": f"⚠️ 系统校验拦截：你在刚才的回答中引用了 {', '.join([f'[{m}]' for m in missing])}，但文末缺失对应文献。为了防止前端重复渲染，请**仅补充输出**遗漏的参考文献条目（无需任何开头客套话和重复正文）。",
                                    }
                                )
                                continue  # 继续下一轮循环，直接将补充内容流式推送给前端

                    await self._save_session()

                    # 💡 策略代码块检测：扫描完整回复中的 Python 代码块，识别包含 backtest/deploy 关键字的策略代码
                    if collected_content:
                        strategy_pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
                        for match in strategy_pattern.finditer(collected_content):
                            code = match.group(1).strip()
                            if any(kw in code for kw in ["backtest", "deploy", "Backtest", "Deploy"]):
                                yield {"type": "strategy_code", "code": code}

                    return
            except Exception as e:
                import traceback

                self.console.print("\n[bold red]❌ [Agent API Error - Stream] 底层调用发生异常:[/bold red]")
                self.console.print(f"[red]{traceback.format_exc()}[/red]")

                yield {"type": "error", "content": f"\n❌ [Agent API Error]: {e}"}
                return

        # 💡 强制熔断恢复策略：5 轮工具调用耗尽后，强制 LLM 输出最终结论
        print("⚠️ [Agent Stream] 达到最大思考循环次数，启动强制熔断恢复策略。")
        try:
            self.messages.append(
                {
                    "role": "user",
                    "content": "⚠️ 系统强制指令：你的思考与工具调用次数已达上限。请立即停止尝试使用工具，仅根据当前上下文中已获取到的数据，给出一个最终的分析总结。",
                }
            )

            final_content = ""
            # 💡 使用 pro 模型进行深度分析总结，提升最终结论质量
            response = await self.client.chat.completions.create(
                model=self.pro_model, messages=cast(Any, self.messages), temperature=0.0, stream=True
            )

            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield {"type": "reasoning_chunk", "content": reasoning}
                if delta.content:
                    final_content += delta.content
                    yield {"type": "text_chunk", "content": delta.content}

            self.messages.append({"role": "assistant", "content": final_content if final_content else None})
            await self._save_session()
        except Exception as e:
            print(f"❌ [Agent Stream] 强制恢复失败: {e}")
            yield {"type": "error", "content": f"\n❌ 强制恢复失败: {e}"}
