"""ScreenerService 主类：组合所有 Mixin 并提供 RAG 语料管理 + 私有规则 CRUD + 结果总结"""

import asyncio
import os
import re
from typing import Any, Dict, List

from backend.core import models
from backend.core.database import SessionLocal, engine
from backend.services.llm_service import llm_service
from backend.services.screener.daemons import DaemonMixin
from backend.services.screener.dsl_parser import DslParserMixin
from backend.services.screener.nlp_translator import NlpTranslatorMixin


class ScreenerService(NlpTranslatorMixin, DslParserMixin, DaemonMixin):
    """
    选股器后台服务
    负责转译 LLM 结构化 JSON、调用券商 API 执行过滤并执行定时订阅任务。
    """

    def __init__(self):
        self._rag_corpus = []
        self.reload_rag_corpus()

    def reload_rag_corpus(self):
        """重载本地向量数据库检索引擎 (支持热更新)"""
        # 1. 默认内置核心指标，作为文件加载失败时的兜底
        default_corpus = [
            {
                "desc": "毛利率 gross margin",
                "rule": "- 毛利率(gross_margin) -> GROSS_PROFIT_RATIO (financial)",
            },  # noqa: E501
            {
                "desc": "营业利润率 operating margin",
                "rule": "- 营业利润率(operating_margin) -> OPERATING_MARGIN_TTM (financial)",
            },  # noqa: E501
            {
                "desc": "经营现金流 operating cash flow",
                "rule": "- 经营现金流(operating_cash_flow) -> OPERATING_CASH_FLOW_TTM (financial)",
            },  # noqa: E501
            {
                "desc": "盈利现金覆盖率 cash cover",
                "rule": "- 盈利现金覆盖率(cash_cover) -> NET_PROFIT_CASH_COVER_TTM (financial)",
            },  # noqa: E501
            {
                "desc": "资产负债率 debt ratio",
                "rule": "- 资产负债率(debt_ratio) -> DEBT_TO_ASSETS (financial)",
            },  # noqa: E501
            {
                "desc": "产权比率 debt equity ratio",
                "rule": "- 产权比率(debt_equity_ratio) -> PROPERTY_RATIO (financial)",
            },  # noqa: E501
            {
                "desc": "流动比率 current ratio",
                "rule": "- 流动比率(current_ratio) -> CURRENT_RATIO (financial)",
            },  # noqa: E501
            {
                "desc": "PE历史百分位 pe percentile",
                "rule": "- PE历史百分位(pe_percentile) -> HIST_PERCENTILE_PE (featured)",
            },  # noqa: E501
            {
                "desc": "营收同比增长率 revenue growth",
                "rule": "- 营收同比增长率(revenue_growth) -> REVENUE_GROWTH (financial)",
            },  # noqa: E501
            {
                "desc": "净利润同比增长率 net profit growth",
                "rule": "- 净利润同比增长率(net_profit_growth) -> NET_PROFIT_GROWTH (financial)",
            },  # noqa: E501
            {
                "desc": "EPS同比增长率 eps growth",
                "rule": "- EPS同比增长率(eps_growth) -> EPS_GROWTH_RATE (financial)",
            },  # noqa: E501
            {
                "desc": "ROE同比增长率 roe growth",
                "rule": "- ROE同比增长率(roe_growth) -> ROE_GROWTH_RATE (financial)",
            },  # noqa: E501
            {
                "desc": "放量 企稳 量比 爆量 volume up surge stabilize",
                "rule": "- 放量/量比(volume_ratio) -> 必须映射为 VOLUME_MULTIPLE (simple)，代表当前成交量相对过去均量的倍数。例如放量要求 min_value: 1.5 或 2.0；企稳(stabilize) -> 映射为 PRICE_CHANGE_PCT (accumulate) 限制波动(如 min_value: -0.03, max_value: 0.03)",
            },  # noqa: E501
            {
                "desc": "上市天数 上市时间 次新股 listed days",
                "rule": "- 上市时间/上市天数/次新股(listed_days) -> LISTED_DAYS (simple)，注意：大模型需自行将年/月换算为绝对天数，如1年即 min_value: 365.0；不满3个月即 max_value: 90.0",
            },  # noqa: E501
            {
                "desc": "上海 A股 上证 沪市 沪股 上海证券交易所",
                "rule": '- 市场指定: 沪市/上证 -> 请严格确保最终 JSON 的 markets 数组中包含 "SH"，不要混淆为 SZ',
            },  # noqa: E501
            {
                "desc": "深圳 A股 深证 深市 深股 深圳证券交易所",
                "rule": '- 市场指定: 深市/深证 -> 请严格确保最终 JSON 的 markets 数组中包含 "SZ"，不要混淆为 SH',
            },  # noqa: E501
            {
                "desc": "A股 中国股市",
                "rule": '- 市场指定: A股/中国股市 -> 请严格确保最终 JSON 的 markets 数组中同时包含 "SH" 和 "SZ"，绝对不能写成 "CN"。',
            },  # noqa: E501
            {
                "desc": "日本 日本股市 日股 东京证券交易所",
                "rule": '- 市场指定: 日本/日股 -> 请确保 markets 数组包含 "JP"',
            },  # noqa: E501
            {
                "desc": "新加坡 新加坡股市 SGX",
                "rule": '- 市场指定: 新加坡 -> 请确保 markets 数组包含 "SG"',
            },  # noqa: E501
            {
                "desc": "英国 伦敦股市 LSE",
                "rule": '- 市场指定: 英国 -> 请确保 markets 数组包含 "UK"',
            },  # noqa: E501
            {
                "desc": "换手率 turnover rate ratio",
                "rule": "- 换手率(turnover_rate) -> 必须映射为 TURNOVER_RATIO (accumulate)，这是一个百分比指标（如 3% 输出 0.03），绝对不能错写成 AVG_TURNOVER(成交额)！",
            },  # noqa: E501
            {
                "desc": "成交额 交易额 turnover amount",
                "rule": "- 成交额/交易额(turnover) -> 必须映射为 AVG_TURNOVER (accumulate)，这是一个代表资金规模的绝对数值，绝对不能错写成 换手率(TURNOVER_RATIO)！",
            },  # noqa: E501
            {
                "desc": "创历史新高 突破52周新高 即将新高 接近最高点 price to 52w high",
                "rule": '- 创历史新高/接近52周新高(price_to_52w_high) -> 必须映射为 PRICE_TO_52W_HIGH (simple)，代表(现价-52周高)/52周高，需转换为真实小数格式。若是"即将创新高/接近新高"，建议设 min_value: -0.05, max_value: 0.0；若是"已突破新高"，建议设 min_value: 0.0',
            },  # noqa: E501
            {
                "desc": "跳空高开 高开 gap up",
                "rule": '- 跳空高开(gap_up) -> 由于底层不支持跨字段计算，请将其降级为技术形态：在最外层 technical_patterns 数组中加入 "gap_up"。',
            },  # noqa: E501
            {
                "desc": "连续放量 连续三天放量 volume surge 3 days",
                "rule": '- 连续放量/连续3天放量(continuous volume surge) -> 由于底层量比不支持时间序列，请将其降级为技术形态：在最外层 technical_patterns 数组中加入 "volume_surge_3d"。',
            },  # noqa: E501
            {
                "desc": "缩量 地量 萎缩 极度萎缩 volume shrink",
                "rule": "- 缩量/地量(volume_shrink) -> 必须映射为 VOLUME_MULTIPLE (simple)，设置 max_value: 0.5（代表当前量比仅为过去的一半及以下）。",
            },  # noqa: E501
            {
                "desc": "均线附近 长期均线 多头排列 均线上方 moving average",
                "rule": "- 均线附近/均线多头(moving_average) -> 映射为 LONG_ARRANGEMENT (kline_shape)，代表价格处于均线系统上方或多头排列企稳形态。",
            },  # noqa: E501
            {
                "desc": "业绩预增 业绩预告 盈利预喜 earnings guidance",
                "rule": "- 业绩预增/预告(earnings_guidance) -> 请映射为 NET_PROFIT_GROWTH (financial)，并将 term 设为 SURPRISE_LATEST（代表财报预测/快报），设置 min_value > 0（例如预增50%即 min_value: 0.5）。",
            },  # noqa: E501
            {
                "desc": "扭亏为盈 业绩扭亏 turnaround",
                "rule": "- 扭亏为盈(turnaround) -> 必须输出两个独立的 NET_PROFIT (financial) 条件：1. term 设为 SURPRISE_LATEST，min_value: 0.0（代表预告/快报当期盈利）；2. term 设为 ANNUAL，max_value: 0.0（代表上一年度亏损）。",
            },  # noqa: E501
            {
                "desc": "连续分红 连续派息 历史分红 continuous dividend",
                "rule": '- 连续N年分红/派息(continuous_dividend) -> 必须映射为 DIVIDEND_RATIO，且 type 必须设为 financial，term 设为 ANNUAL，min_value: 0.0，lower_included: false，continuous_period: N。⚠️注意：如果同时有"当前股息率>x%"要求，请务必分为两个独立的 filter 输出！',
            },  # noqa: E501
            {
                "desc": "短期债务 短期负债 流动负债 没有短期负债 short term debt",
                "rule": '- 短期债务/流动负债(short_term_debt) -> 映射为 CURRENT_DEBT_RATIO (financial)。若是要求"没有短期负债/无短期债务压力"，请严格限制 max_value: 0.1（代表流动负债占总负债极小），或者配合使用 QUICK_RATIO (financial) 设置 min_value: 1.0 剔除存货水分。',
            },  # noqa: E501
            {
                "desc": "行业 板块 概念 银行股 科技股 医药股 消费股 sector industry plate",
                "rule": '- 行业/板块/概念(industry/plate) -> 映射为 type: "plate"（或 "exclude_plate" 用于剔除），并将具体的行业名称（如 ["银行", "半导体", "医药", "消费"]）放入 value 数组中。注意：不需要自己猜测富途板块代码，直接填中文名称即可！',
            },  # noqa: E501
            {
                "desc": "研发投入 研发费用 R&D research",
                "rule": '- 研发投入/研发费用(R&D) -> 富途底层暂不支持直接筛选研发数据！请忽略此数值条件，但必须根据上下文语义（如"科技先锋"）转化为行业筛选：输出 field: "STOCK_PLATE", type: "plate", value: ["科技"] 等。',
            },  # noqa: E501
            {
                "desc": "高管增持 高管买入 内幕交易 净买入 insider net buy",
                "rule": '- 高管增持/净买入(insider_buy) -> 富途底层不支持，必须降级为另类数据二次过滤：请在最外层 technical_patterns 数组中加入 "insider_net_buy"。',
            },  # noqa: E501
        ]

        self._rag_corpus = []

        # 2. 尝试从本地 CSV 动态加载数百个额外指标
        import pandas as pd

        csv_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "indicators.csv")  # noqa: E501
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                if "desc" in df.columns and "rule" in df.columns:
                    for _, row in df.iterrows():
                        if pd.notna(row["desc"]) and pd.notna(row["rule"]):
                            self._rag_corpus.append(
                                {
                                    "desc": str(row["desc"]).strip(),
                                    "rule": str(row["rule"]).strip(),
                                }
                            )  # noqa: E501
                    print(f"✅ [Screener] 成功从 CSV 动态加载 {len(self._rag_corpus)} 条指标 RAG 规则库！")  # noqa: E501
            except Exception as e:
                print(f"⚠️ [Screener] 从 CSV 加载外部指标失败，使用兜底规则: {e}")

        # 3. 如果没读到任何外部数据，使用硬编码兜底
        if not self._rag_corpus:
            self._rag_corpus = default_corpus

        # 4. 初始化 Embedding 模型 (支持 OpenAI 兼容接口或本地 SentenceTransformers)
        emb_api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        if emb_api_key:
            import requests

            emb_base_url = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            emb_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            print(f"☁️ [Screener] 检测到云端 Embedding 密钥，启用 {emb_model} 模型进行向量化")  # noqa: E501

            def get_embeddings(texts):
                headers = {
                    "Authorization": f"Bearer {emb_api_key}",
                    "Content-Type": "application/json",
                }  # noqa: E501
                res = requests.post(
                    f"{emb_base_url}/embeddings",
                    headers=headers,
                    json={"input": texts, "model": emb_model},
                    timeout=30,
                )  # noqa: E501
                if res.status_code == 200:
                    return [d["embedding"] for d in res.json().get("data", [])]
                print(f"⚠️ OpenAI Embedding API 失败: {res.text}")
                return []

            self._embed_func = get_embeddings
        else:
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
                print("💻 [Screener] 启用本地 SentenceTransformer 模型进行向量化")
                self._embed_func = lambda texts: model.encode(texts).tolist()
            except ImportError:
                print("⚠️ [Screener] 未安装 sentence_transformers 且未配置 API Key，将降级全量返回规则。")  # noqa: E501
                self._embed_func = None

        embed_func = self._embed_func
        if not embed_func:
            self._pg_enabled = False
            return {"count": len(self._rag_corpus), "warning": "missing_deps"}

        # 5. 向量化并灌入 PostgreSQL (pgvector)
        try:
            from sqlalchemy import text

            with engine.begin() as conn:
                self._pg_enabled = conn.dialect.name == "postgresql"
                if not self._pg_enabled:
                    print("⚠️ [Screener] 当前非 PostgreSQL 数据库，自动降级为全量规则兜底模式。")  # noqa: E501
                    return {"count": len(self._rag_corpus), "warning": "not_postgres"}

                # ⚠️ 极度重要：仅清理系统的公共冷启动知识库，绝对保留用户的私有规则 (user_id IS NOT NULL)  # noqa: E501
                conn.execute(text("DELETE FROM quant_screener_rules WHERE user_id IS NULL"))  # noqa: E501

                docs = [doc["desc"] for doc in self._rag_corpus]
                metadatas = [{"rule": doc["rule"]} for doc in self._rag_corpus]
                ids = [f"rule_{i}" for i in range(len(self._rag_corpus))]

                from rich.progress import track

                batch_size = 60
                batches = list(range(0, len(docs), batch_size))

                for i in track(
                    batches,
                    description="[cyan]🧠 正在向量化 RAG 规则并灌入 PostgreSQL...[/cyan]",
                ):  # noqa: E501
                    b_docs = docs[i : i + batch_size]
                    b_metas = metadatas[i : i + batch_size]
                    b_ids = ids[i : i + batch_size]

                    b_embs = embed_func(b_docs)
                    if not b_embs:
                        continue  # noqa: E701

                    for j in range(len(b_docs)):
                        # pgvector 直接接受形如 '[0.1, 0.2, ...]' 的字符串格式
                        emb_str = f"[{','.join(map(str, b_embs[j]))}]"
                        # 💡 动态提取规则类型，作为标量过滤 (Scalar Filtering) 的测试字段  # noqa: E501
                        rule_type = "financial" if "financial" in b_metas[j]["rule"] else "simple"  # noqa: E501
                        conn.execute(
                            text("""
                            INSERT INTO quant_screener_rules (id, desc_text, rule_text, rule_type, embedding)
                            VALUES (:id, :desc, :rule, :rtype, CAST(:emb AS vector))
                            ON CONFLICT (id) DO UPDATE SET
                                desc_text = EXCLUDED.desc_text,
                                rule_text = EXCLUDED.rule_text,
                                rule_type = EXCLUDED.rule_type,
                                embedding = EXCLUDED.embedding
                        """),
                            {
                                "id": b_ids[j],
                                "desc": b_docs[j],
                                "rule": b_metas[j]["rule"],
                                "rtype": rule_type,
                                "emb": emb_str,
                            },
                        )  # noqa: E501

            print(f"✅ [Screener] PostgreSQL (pgvector) 引擎就绪！共完成 {len(self._rag_corpus)} 条规则的嵌入向量化。")  # noqa: E501
            return {"count": len(self._rag_corpus)}
        except Exception as e:
            print(f"⚠️ [Screener] Postgres 向量存储初始化异常: {e}")
            self._pg_enabled = False
            return {"count": len(self._rag_corpus), "warning": "db_error"}

    async def add_custom_rule(self, desc_text: str, rule_text: str, user_id: int) -> Dict[str, Any]:  # noqa: E501
        """用户上传并向量化私有选股规则"""
        embed_func = getattr(self, "_embed_func", None)
        if not getattr(self, "_pg_enabled", False) or not embed_func:
            return {
                "status": "error",
                "message": "向量数据库未启用，无法保存私有规则。",
            }  # noqa: E501

        import uuid

        rule_id = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
        rule_type = "financial" if "financial" in rule_text else "simple"

        def _insert():
            # 1. 向量化用户上传的自然语言描述
            embs = embed_func([desc_text])
            if not embs:
                raise ValueError("Embedding 生成失败")

            with SessionLocal() as db:
                # 2. 存入数据库，强绑定 user_id 标签
                new_rule = models.ScreenerRule(
                    id=rule_id,
                    desc_text=desc_text,
                    rule_text=rule_text,
                    rule_type=rule_type,
                    user_id=user_id,
                    embedding=embs[0],
                )
                db.add(new_rule)
                db.commit()
            return rule_id

        try:
            r_id = await asyncio.to_thread(_insert)
            return {"status": "success", "id": r_id, "message": "私有规则添加成功"}
        except Exception as e:
            print(f"⚠️ [Screener] 添加私有规则失败: {e}")
            return {"status": "error", "message": str(e)}

    async def get_custom_rules(self, user_id: int) -> List[Dict[str, Any]]:
        """获取指定用户的私有规则列表"""
        if not getattr(self, "_pg_enabled", False):
            return []

        def _get():
            with SessionLocal() as db:
                rules = db.query(models.ScreenerRule).filter(models.ScreenerRule.user_id == user_id).all()  # noqa: E501
                return [
                    {
                        "id": r.id,
                        "desc": r.desc_text,
                        "rule": r.rule_text,
                        "type": r.rule_type,
                    }
                    for r in rules
                ]  # noqa: E501

        try:
            return await asyncio.to_thread(_get)
        except Exception as e:
            print(f"⚠️ [Screener] 获取私有规则失败: {e}")
            return []

    async def delete_custom_rule(self, rule_id: str, user_id: int) -> bool:
        """安全删除指定的私有规则（强依赖 user_id 鉴权防止越权删除）"""
        if not getattr(self, "_pg_enabled", False):
            return False

        def _del():
            with SessionLocal() as db:
                rule = (
                    db.query(models.ScreenerRule)
                    .filter(
                        models.ScreenerRule.id == rule_id,
                        models.ScreenerRule.user_id == user_id,
                    )
                    .first()
                )
                if rule:
                    db.delete(rule)
                    db.commit()
                    return True
                return False

        try:
            return await asyncio.to_thread(_del)
        except Exception as e:
            print(f"⚠️ [Screener] 删除私有规则失败: {e}")
            return False

    async def summarize_results(self, stocks: List[Dict[str, Any]]) -> str:
        """一键总结前端传入的选股器结果"""
        if not stocks:
            return "暂无选股结果可供分析。"

        # 仅取前 10 只龙头股进行分析，防范大模型 Token 溢出并控制生成速度
        top_stocks = stocks[:10]

        # 💡 并发拉取这 10 只股票的最新一条新闻
        async def _fetch_latest_news(ticker):
            try:
                is_asian = any(x in ticker.upper() for x in ["HK", "SH", "SZ"]) or ticker.isdigit()  # noqa: E501
                if is_asian:
                    from backend.services.data_source_router import data_source_router

                    res = await data_source_router.fetch_akshare("news", ticker=ticker)
                else:
                    from backend.services.finnhub_service import finnhub_service

                    res = await finnhub_service.get_company_news(ticker, days_back=3)
                if res.get("status") == "success" and res.get("data"):
                    return res["data"][0].get("headline", "")
            except Exception:
                pass
            return ""

        news_list = await asyncio.gather(
            *[_fetch_latest_news(r["symbol"]) for r in top_stocks],
            return_exceptions=True,
        )  # noqa: E501

        stock_contexts = []
        for r, news in zip(top_stocks, news_list):
            if isinstance(news, BaseException):
                news = ""  # noqa: E701
            chg = r.get("chg", r.get("price_change_pct", r.get("change_rate", 0)))
            news_str = f", 最新动态: {news}" if news else ""
            stock_contexts.append(f"- {r.get('name', r['symbol'])} ({r['symbol']}): 涨跌幅 {chg:.2f}%{news_str}")  # noqa: E501

        stocks_info_str = "\n".join(stock_contexts)

        prompt = f"你是华尔街顶级量化分析师。以下是用户刚刚使用选股器筛选出的前 {len(top_stocks)} 只标的及最新盘面动态：\n\n{stocks_info_str}\n\n请你用毒舌、专业的金融黑话，写一份简短的《AI 选股结果一键洞察》。\n要求：\n1. 提炼出这批股票共有的 1-2 个核心炒作概念或主线属性。\n2. 点评最具代表性的 2-3 只龙头股。\n3. 提示目前追高或介入的系统性风险。\n4. 格式使用清晰的 Markdown，字数控制在 400 字以内。"  # noqa: E501

        try:
            resp = await llm_service.get_client().chat.completions.create(
                model=llm_service.get_model(),
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}],
            )  # noqa: E501
            content = resp.choices[0].message.content
            report = content.strip() if content else "暂无分析结果"
            return re.sub(r"\n```$", "", re.sub(r"^```[a-zA-Z]*\n", "", report)).strip()
        except Exception as e:
            print(f"⚠️ [Screener Service] LLM 总结失败: {e}")
            return f"生成分析报告失败: {e}"


# 导出全局单例
screener_service = ScreenerService()
