"""NLP → DSL 转译 Mixin：自然语言选股条件智能转译为结构化 JSON"""

import asyncio
import hashlib
import json
import random
import re
from typing import List, Optional

from openai.types.chat import ChatCompletionMessageParam
from pydantic import ValidationError

from backend.core.redis_client import redis_client
from backend.services.llm_service import llm_service
from backend.services.screener.models import ScreenerDecision


class NlpTranslatorMixin:
    """提供 NLP → DSL 转译能力的 Mixin"""

    def _normalize_nlp_query(self, query: str) -> str:
        """
        对自然语言查询进行标准化处理，提高缓存命中率。
        包括转换为小写、移除标点符号、将连续空格替换为单空格。
        """
        # 1. 转换为小写
        normalized_query = query.lower()
        # 2. 移除所有非字母、数字、中文和空格的字符 (标点符号)
        # re.UNICODE 标志用于正确处理 Unicode 字符集 (如中文)
        normalized_query = re.sub(r"[^\w\s\u4e00-\u9fa5]", " ", normalized_query, flags=re.UNICODE)  # noqa: E501
        # 3. 将连续的空格替换为单个空格
        normalized_query = re.sub(r"\s+", " ", normalized_query)
        # 4. 移除首尾空格
        return normalized_query.strip()

    async def _retrieve_relevant_fields(self, query: str, user_id: Optional[int] = None) -> str:  # noqa: E501
        """
        [RAG 动态检索基座]
        """
        from backend.core import models
        from backend.core.database import SessionLocal

        embed_func = getattr(self, "_embed_func", None)
        if not getattr(self, "_pg_enabled", False) or not embed_func:
            return "\n".join([str(doc.get("rule", "")) for doc in self._rag_corpus])

        try:

            def _query_vectordb():
                q_emb = embed_func([query])
                if not q_emb:
                    return []  # noqa: E701

                from sqlalchemy import or_

                with SessionLocal() as db:
                    # ==== 💡 SQLAlchemy 混合检索 (Hybrid Search) ====
                    # pgvector 支持直接在 ORM 中调用 .cosine_distance()
                    distance_col = models.ScreenerRule.embedding.cosine_distance(q_emb[0])  # noqa: E501

                    results = (
                        db.query(models.ScreenerRule, distance_col.label("distance"))
                        # 0. 🔐 强制多租户标量过滤 (Multi-Tenant Filter): 仅检索当前用户的私有规则，以及系统的公共规则  # noqa: E501
                        .filter(
                            or_(
                                models.ScreenerRule.user_id == user_id,
                                models.ScreenerRule.user_id.is_(None),
                            )
                        )  # noqa: E501
                        # 1. 标量过滤 (Scalar Filter): 假设我们只关心 "financial" 和 "simple" 这两个大类的指标  # noqa: E501
                        .filter(models.ScreenerRule.rule_type.in_(["financial", "simple"]))  # noqa: E501
                        # 2. 向量过滤 (Vector Filter): 余弦距离阈值卡控 (必须小于 0.6)
                        .filter(distance_col < 0.6)
                        # 3. 向量排序 (Vector Sort): 按相似度从高到低 (距离从低到高) 排序  # noqa: E501
                        .order_by(distance_col.asc())
                        .limit(5)
                        .all()
                    )

                    top_rules = []
                    for rule, distance in results:
                        # 计算余弦相似度百分比：(1 - distance) * 100
                        similarity_pct = (1.0 - distance) * 100
                        top_rules.append(f"{rule.rule_text} (匹配度: {similarity_pct:.1f}%)")  # noqa: E501

                    return top_rules

            top_rules = await asyncio.to_thread(_query_vectordb)
            if top_rules:
                return "\n".join(top_rules)
            return "\n".join([str(doc.get("rule", "")) for doc in self._rag_corpus])
        except Exception as e:
            print(f"⚠️ [Screener RAG] 向量检索异常，已安全降级至返回全量规则兜底: {e}")
            return "\n".join([str(doc.get("rule", "")) for doc in self._rag_corpus])

    async def translate_nlp_to_dsl(self, nlp_query: str, user_id: Optional[int] = None) -> str:  # noqa: E501
        """调用大模型将自然语言智能转译为强类型的底层筛选 JSON"""
        # 1. ⚡ Redis 语义缓存：直接计算 MD5，若存在则实现毫秒级秒回
        normalized_nlp_query = self._normalize_nlp_query(nlp_query)
        query_hash = hashlib.md5(normalized_nlp_query.encode("utf-8")).hexdigest()
        # 💡 添加 v8 版本号：新增全市场兜底逻辑，废弃之前遗漏市场的残缺 JSON
        cache_key = f"quant:screener:nlp_cache:v8:{query_hash}"

        try:
            cached_dsl = await redis_client.get(cache_key)
            if cached_dsl:
                print(f"⚡ [Screener] NLP 语义缓存命中，直接秒回: {nlp_query} (归一化查询: {normalized_nlp_query})")  # noqa: E501
                return cached_dsl.decode("utf-8") if isinstance(cached_dsl, bytes) else str(cached_dsl)  # noqa: E501
        except Exception as e:
            print(f"⚠️ [Screener] Redis 读取 NLP 缓存失败: {e}")

        if not hasattr(self, "_nlp_locks"):
            self._nlp_locks = {}

        if cache_key not in self._nlp_locks:
            self._nlp_locks[cache_key] = asyncio.Lock()

        async with self._nlp_locks[cache_key]:
            try:
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return cached_double.decode("utf-8") if isinstance(cached_double, bytes) else str(cached_double)  # noqa: E501
            except Exception:
                pass

            # 1. 执行 RAG 动态召回，获取与当前用户自然语言最相关的可用指标列表
            rag_fields_str = await self._retrieve_relevant_fields(nlp_query, user_id)

            # 2. 组装终极 Prompt (高频常驻指标 + RAG 注入指标)
            prompt = f"""你是一个顶级量化研发专家。请将用户的自然语言选股条件转换为标准的 JSON 格式。

    【字段映射规则 - 严格白名单】
    ⚠️ 绝对禁止虚构字段！你必须且只能从以下列表的精确字段名中进行挑选（包括对应的 type）。遇到不支持的指标（如"营收萎缩"），必须转换为已有相近指标（如 REVENUE_GROWTH 最大值设为0），如果完全无法对应则直接忽略该条件。绝不允许自己捏造任何英文变量名！

    📌 高频核心指标（常驻）：
    - 市值(mktcap) -> MARKET_CAP (simple)
    - 市盈率(pe) -> PE_TTM (simple)
    - 市净率(pb) -> PB (simple)
    - PE历史分位 -> HIST_PERCENTILE_PE (featured)
    - PB历史分位 -> HIST_PERCENTILE_PB (featured)
    - PS历史分位 -> HIST_PERCENTILE_PS (featured)
    - 最新价(price) -> PRICE (simple)
    - 成交量(vol) -> AVG_VOLUME (accumulate)
    - 成交额(turnover) -> AVG_TURNOVER (accumulate)
    - 换手率(turnover_rate) -> TURNOVER_RATIO (accumulate)
    - 涨跌幅(change) -> PRICE_CHANGE_PCT (accumulate)
    - 振幅(amplitude) -> AMPLITUDE (accumulate)
    - 净资产收益率(roe) -> ROE (financial)
    - 资产回报率(roa) -> ROA_TTM (financial)
    - 股息率(div_yield) -> DIVIDEND_RATIO (simple)
    - 滚动股息率(div_yield_ttm) -> DIVIDEND_RATIO (simple)
    - 每股收益(eps) -> BASIC_EPS (financial)
    - 净利润(net_profit) -> NET_PROFIT (financial)
    - 营收(revenue) -> REVENUE (financial)
    - 量比/放量(volume_ratio) -> VOLUME_MULTIPLE (simple) (例如放量1.2倍即 min_value: 1.2)

    🎯 动态补充指标（RAG 根据你的意图召回的可能需要的冷门指标）：{rag_fields_str}

    【数值换算规则 - 极度重要】
    1. 所有金额单位必须计算为绝对纯数字！例如："100M" 或 "1000万" 必须输出为 10000000.0，"1亿" 必须输出为 100000000.0，"100亿" 为 10000000000.0。
    2. ⚠️ 富途底层规范 - 严格小数输入：
       - **所有比率(Ratio)、利润率(Margin)、百分位(Percentile)、ROE/ROA等百分比指标**: 必须统一输出为**真实小数格式**！例如："ROE>15%" → 0.15；"PE历史分位<40%" → 0.40；"营业利润率>10%" → 0.10。
       - **财务倍数比值指标 (如流动比率, 产权比率)**: 必须输出真实比值！例如："流动比率>2" → 2.0；"产权比率<1" → 1.0。
       - **绝对数值指标 (如市盈率, 市净率)**: 保持原始数值。例如："PE<20" → 20.0。
    3. "等于 10" 转化为 min_value: 9.5, max_value: 10.5。
    4. 财务周期："最新单季"输出 "LATEST"；"中报"输出 "Q6"；"三季报"输出 "Q9"；年报输出 "ANNUAL"。注意：富途不支持 term="TTM"，凡是要求"滚动/TTM"的指标请直接选择自带 _TTM 后缀的独立字段（如 ROA_TTM, PE_TTM），且不需要为其指定 term。

    【大师法则平替】
    - Piotroski F-Score: NET_PROFIT > 0, OPERATING_CASH_FLOW_TTM > 0, NET_PROFIT_CASH_COVER_TTM > 1.0
    - Graham 估值/债务安全: HIST_PERCENTILE_PE < 0.40, CURRENT_RATIO >= 2.0, PROPERTY_RATIO < 1.0
    - Buffett 护城河: ROE > 0.15, OPERATING_MARGIN_TTM > 0.10, PROPERTY_RATIO < 1.0

    【原生技术/K线形态支持】
    富途原生支持海量技术形态过滤，必须以对象结构存入 filters 数组中，禁止降级到 Pandas 二次过滤！
    - 具体技术指标数值过滤与获取 (type: indicator): 例如 RSI, MACD, KDJ, BOLL, EMA 等。支持 min_value / max_value。必须指定 period (如 "K_DAY")。
    - 技术形态 (type: indicator_pattern): MACD_GOLD_CROSS (MACD金叉), MACD_DEATH_CROSS (死叉), RSI_OVERSOLD (RSI超卖), RSI_OVERBOUGHT (超买), KDJ_GOLD_CROSS (KDJ金叉), BOLL_BREAK_UPPER (突破布林带上轨), RSI_BOTTOM_DIVERGE (RSI底背离), RSI_TOP_DIVERGE (RSI顶背离), MACD_BOTTOM_DIVERGE (MACD底背离), MACD_TOP_DIVERGE (MACD顶背离) 等。必须指定 period (如 "K_DAY", "K_60M")。
    - K线形态 (type: kline_shape): LONG_ARRANGEMENT (多头排列), SHORT_ARRANGEMENT (空头排列), MORNING_STAR (曙光初现), THREE_RED_SOLDIERS (红三兵) 等。必须指定 period。
    - 指标位置 (type: indicator_positional): 例如价格上穿均线，field 填 PRICE，second_indicator 填 MA，position 填 CROSS_UP，period 填 K_DAY。
    - 资金流/经纪商/期权: type 填 broker 或 option。
    - 💡 高级形态降级: 若用户要求 "VCP形态" (波动率收缩) / "跳空高开" / "连续三天放量" 等富途不支持的复杂形态，请将其写入最外层的 `technical_patterns` 字符串数组中，值为 "vcp_pattern", "gap_up", "volume_surge_3d" 等。

    【时序逻辑处理法则】
    如果用户要求"连续N年/期增长"或"连续N年/期为正/盈利"：
    1. 请不要拆分为多个独立的 filter。
    2. 必须定位到对应的 **增长率 (GROWTH_RATE)** 或本体指标，并使用 `continuous_period` 属性！
       - 例如："ROIC连续3年增长" -> {{"field": "ROIC_GROWTH_RATE", "type": "financial", "term": "ANNUAL", "min_value": 0.0, "lower_included": false, "continuous_period": 3}}
       - 例如："连续5年持续盈利" -> {{"field": "NET_PROFIT", "type": "financial", "term": "ANNUAL", "min_value": 0.0, "lower_included": false, "continuous_period": 5}}
       - 例如："连续5年分红" -> {{"field": "DIVIDEND_RATIO", "type": "financial", "term": "ANNUAL", "min_value": 0.0, "lower_included": false, "continuous_period": 5}}

    如果用户要求某指标的长期均值 (如"过去5年平均ROE>20%")：
    使用 `period_average` (布尔值) 与 `duration` (期数) 组合。
       - 例如："近5年平均ROE>20%" -> {{"field": "ROE", "type": "financial", "term": "ANNUAL", "min_value": 0.20, "period_average": true, "duration": 5}}

    请确保 `dsl_display` 字段非常简洁，使用代码风格概括。⚠️ 注意：dsl_display 中的技术形态（如 RSI底背离、MACD金叉等）以及属性（如 放量、量比等）请务必直接使用**中文**展示，不要使用英文枚举名！例如："US 市值>100亿 PE<20 RSI底背离 放量>1.2"，字数尽量控制在 50 字以内。
    请输出如下 JSON 结构（不要使用代码 标记）：
    {{
      "dsl_display": "market:hk pe:10~20 mktcap:>10B MACD金叉",
      "markets": ["HK"],
      "exclude_st": false,
      "technical_patterns": [],
      "filters": [
         {{"field": "PE_TTM", "type": "simple", "min_value": 10.0, "max_value": 20.0}},
         {{"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 10000000000.0}},
         {{"field": "MACD_GOLD_CROSS", "type": "indicator_pattern", "period": "K_DAY"}}
      ]
    }}"""  # noqa: E501
            messages: List[ChatCompletionMessageParam] = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": nlp_query},
            ]

            max_retries = 2
            result_dsl = ""
            decision = None

            try:
                for attempt in range(max_retries + 1):
                    resp = await llm_service.get_client().chat.completions.create(
                        model=llm_service.get_model(),
                        temperature=0.0,
                        response_format={"type": "json_object"},
                        messages=messages,
                    )
                    result_dsl = resp.choices[0].message.content or ""
                    print(f"🤖 [Screener] LLM 原始输出 DSL JSON (Attempt {attempt + 1}):\n{result_dsl}")  # noqa: E501

                    if not result_dsl or not result_dsl.strip():
                        print("⚠️ [Screener] LLM 返回空内容，重试中...")
                        messages.append(
                            {
                                "role": "user",
                                "content": "你返回了空内容，请重新生成合法的 JSON。",
                            }
                        )  # noqa: E501
                        continue

                    try:
                        decision = ScreenerDecision.model_validate_json(result_dsl)
                        print("✅ [Screener] LLM 输出通过 Pydantic 预验证")
                        break  # 验证成功，跳出循环
                    except ValidationError as ve:
                        print("⚠️ [Screener] LLM 输出未通过预验证，尝试自动修复...")
                        err_msgs = []
                        for err in ve.errors():
                            err_msg = f"错误位置: {err['loc']}, 类型: {err['type']}, 消息: {err.get('msg', '')}"  # noqa: E501
                            print(f"   - {err_msg}")
                            err_msgs.append(err_msg)

                        if attempt < max_retries:
                            # 将助手的不合法输出和验证报错反馈给模型进行自我修复
                            messages.append({"role": "assistant", "content": result_dsl})  # noqa: E501
                            messages.append(
                                {
                                    "role": "user",
                                    "content": "你的 JSON 输出不符合 Pydantic 校验规范，报错如下：\n"
                                    + "\n".join(err_msgs)
                                    + "\n请修正这些错误并重新输出完整的 JSON 对象。",  # noqa: E501
                                }
                            )
                        else:
                            print("❌ [Screener] 达到最大重试次数，自动修复失败")
                            # 放弃修复，后续交由兜底逻辑处理
                            decision = None

                # 如果经过重试仍然没有有效的 decision，使用兜底
                if not decision:
                    print("⚠️ [Screener] 无法生成合法 JSON，使用兜底默认值")
                    result_dsl = '{"dsl_display": "market:us mktcap:>10B pe:10~50", "markets": ["US"], "exclude_st": false, "filters": [{"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 1e10}, {"field": "PE_TTM", "type": "simple", "term": "TTM", "min_value": 10.0, "max_value": 50.0}]}'  # noqa: E501
                    decision = ScreenerDecision.model_validate_json(result_dsl)

                # 3. 异步缓存成功的转译结果 (自然语言的语义通常不会变，长效缓存 30 天)
                try:
                    if rag_fields_str:
                        # 截取召回内容并作为数组存入 JSON，一并写入 Redis 缓存
                        decision.rag_rules = [r.strip() for r in rag_fields_str.split("\n") if r.strip()]  # noqa: E501

                    # 💡 定制化 JSON 格式：让 RAG 规则展示为单行，其他结构保持树形
                    decision_dict = decision.model_dump(by_alias=True, exclude_none=True)  # noqa: E501
                    rag_rules_data = decision_dict.pop("rag_rules", None)

                    # 确保支持中文字符原样输出
                    result_dsl = json.dumps(decision_dict, indent=2, ensure_ascii=False)

                    if rag_rules_data is not None:
                        rag_str = json.dumps(rag_rules_data, ensure_ascii=False)  # 默认序列化为单行  # noqa: E501
                        if decision_dict:
                            # 剥除末尾的换行和右大括号，将 rag_rules 以单行属性无缝注入
                            result_dsl = result_dsl.rstrip("}\n\r ") + f',\n  "rag_rules": {rag_str}\n}}'  # noqa: E501
                        else:
                            result_dsl = f'{{\n  "rag_rules": {rag_str}\n}}'

                    # 💡 增加随机 Jitter 防雪崩 (30天 + 1~24小时抖动)
                    ttl = 2592000 + random.randint(3600, 86400)
                    await redis_client.setex(cache_key, ttl, result_dsl)
                except Exception as e:
                    print(f"⚠️ [Screener] Redis 写入 NLP 缓存失败或转译修正异常: {e}")

                return result_dsl
            except Exception as e:
                print(f"⚠️ [ScreenerService] DSL 转译失败: {e}")
                fallback = {
                    "dsl_display": "market:hk,sh,sz,us mktcap:>10B pe:10~50",
                    "markets": ["HK", "SH", "SZ", "US"],
                    "exclude_st": False,
                    "filters": [
                        {
                            "field": "MARKET_CAP",
                            "type": "simple",
                            "term": "ANNUAL",
                            "min_value": 1e10,
                        },
                        {
                            "field": "PE_TTM",
                            "type": "simple",
                            "term": "TTM",
                            "min_value": 10.0,
                            "max_value": 50.0,
                        },
                    ],  # noqa: E501
                }
                return json.dumps(fallback, indent=2, ensure_ascii=False)
