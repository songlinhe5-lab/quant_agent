import asyncio
import hashlib
import re
import time
from typing import Any, Dict
from urllib.parse import urlparse

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.metrics import WEB_SCRAPE_FETCH_FAILED, WEB_SCRAPE_FETCH_TOTAL
from backend.core.utils import safe_truncate
from backend.services.search.service import search_service
from hermes_agent.tool_registry import register_tool

from .base import BaseTool
from .web_search_tool import WebSearchTool

logger = structlog.get_logger(__name__)


def _domain_of(url: str) -> str:
    """提取域名用于抓取失败率插桩维度（PR Newswire / HKEX 等反爬域名分桶）。"""
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


@register_tool
class WebScrapeTool(BaseTool):
    """
    网页正文提取工具，利用 Jina Reader API 直接抓取网页并提取纯文本 Markdown。
    """

    name = "fetch_webpage"
    description = "获取指定 URL 网页的正文内容（以 Markdown 格式返回）。当你在搜索结果中看到感兴趣的链接，需要深入阅读完整的研报或新闻原文时调用此工具。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "需要读取正文的具体网页 URL 链接"},
            "query": {
                "type": "string",
                "description": "可选：由于网页可能极长，强烈建议提供此参数以触发 RAG 语义检索。请务必输入极其具体的问题或事实细节（例如：'高管对下个季度的营收和毛利率指引是多少？' 或 '该研报提到的三大看多逻辑和目标价'）。严禁输入诸如'总结'、'财报'、'核心内容'等宽泛废话。",
            },
        },
        "required": ["url"],
    }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def run(self, url: str, query: str = "") -> Dict[str, Any]:
        if not url:
            return {"status": "error", "message": "URL 不能为空"}

        # 💡 安全防线：防范 SSRF 与本地文件读取 (Local File Inclusion) 漏洞
        if not url.lower().startswith(("http://", "https://")):
            return {"status": "error", "message": "非法的 URL 协议。出于安全风控原因，仅允许访问 http(s) 标准网页。"}

        # 💡 拦截 PDF/文档链接，Jina 和 httpx 都无法解析二进制文件
        if url.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
            return {
                "status": "error",
                "message": (
                    f"该链接是文档文件 ({url.split('.')[-1].upper()})，网页抓取工具无法解析二进制文档。\n\n"
                    "💡 建议操作:\n"
                    "1. 使用 web_search 搜索该文档的网页版或摘要\n"
                    "2. 手动下载文档后使用 analyze_financial_report 工具分析本地文件"
                ),
            }

        # 方案 1: 使用 Jina Reader API (优先，专门为大模型优化)
        content = await self._fetch_via_jina(url)

        # 方案 2: Jina 失败时降级到直接 HTTP 抓取
        if content is None:
            content = await self._fetch_via_httpx(url)

        if content is None:
            # 💡 AGENTS.md §2.12 自动降级：Jina + httpx 双路抓取失败（含 403/404/503 反爬拦截，
            #    典型如 PR Newswire / HKEX 披露易），立即切换 web_search 而非死磕单链接。
            domain = _domain_of(url)
            search_query = f"{url} {query}".strip()
            try:
                search_res = await WebSearchTool().run(
                    query=search_query,
                    max_results=5,
                    include_domains=[domain],  # 优先找同站可访问镜像/替代页
                )
            except Exception as e:  # 降级链自身异常不应吞掉原始抓取失败结论
                logger.warning("webscrape_fallback_search_error", url=url, error=repr(e))
                search_res = {"status": "error", "message": repr(e)}

            if search_res.get("status") == "success" and search_res.get("data"):
                logger.info("webscrape_fallback_web_search", url=url, domain=domain)
                return {
                    "status": "degraded",
                    "fallback": "web_search",
                    "source_url": url,
                    "message": (
                        f"网页直接抓取失败（Jina + HTTP 均被拦截，疑似 {domain} 反爬/403-503），"
                        "已自动降级至 web_search 检索同站替代数据源。以下为搜索结果，非原文正文，请谨慎引用。"
                    ),
                    "data": search_res.get("data"),
                }

            # 连 web_search 也失败，才回退原始 error 文案
            return {
                "status": "error",
                "message": (
                    "无法抓取该网页：Jina API、直接 HTTP 抓取、以及自动降级 web_search 均失败\n\n"
                    "💡 建议操作:\n"
                    "1. 尝试从搜索结果中选择其他可访问的链接\n"
                    "2. 或告知用户该网页暂时无法访问"
                ),
            }

        return await self._format_response(url, content, query)

    async def _fetch_via_jina(self, url: str, query: str = "") -> str | None:
        """方案 1: Jina Reader 网页正文提取（经 backend 远程代理，主服务/Hermes 不直连 r.jina.ai）。

        BE-ARCH-07m: 原实现直连 Jina Reader（r.jina.ai 代理域名），违反"Hermes 不得
        直连外部数据源"红线。现统一经 search_service.fetch_webpage →
        data_source_router.fetch_search("jina", url) → data_subservice 子服务
        （持有 Jina API key 与 rate limit）。
        """
        domain = _domain_of(url)
        WEB_SCRAPE_FETCH_TOTAL.labels(source="jina", domain=domain).inc()
        try:
            res = await search_service.fetch_webpage(url, query=query)
        except Exception as e:  # noqa: BLE001 - 远程代理异常视为抓取失败，进入降级链
            logger.warning("jina_proxy_failed", url=url, error=repr(e))
            WEB_SCRAPE_FETCH_FAILED.labels(source="jina", domain=domain, reason="proxy_error").inc()
            return None

        if res.get("status") != "success":
            logger.warning("jina_proxy_unsuccessful", url=url, message=res.get("message"))
            WEB_SCRAPE_FETCH_FAILED.labels(source="jina", domain=domain, reason="empty_or_blocked").inc()
            return None

        content = res.get("data", {}).get("content") if isinstance(res.get("data"), dict) else None
        if not content:
            return None

        # 💡 利用正则清洗 Markdown 中的冗余图片和超链接
        content = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", content)
        content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)

        # 💡 拦截动态反爬与 JS 护盾
        if len(content) < 200 or "Please enable JS" in content or "访问受限" in content or "Just a moment" in content:
            logger.warning("jina_anti_bot_blocked", url=url)
            WEB_SCRAPE_FETCH_FAILED.labels(source="jina", domain=domain, reason="anti_bot").inc()
            return None

        return content

    async def _fetch_via_httpx(self, url: str) -> str | None:
        """方案 2: Jina 远程代理重试（带空 query 二次尝试，覆盖 Jina 对部分站点首次失败）。

        原实现为直连目标站 httpx 抓取（Hermes 直连外部源，违反 07m 红线），已移除。
        统一改为复用 Jina 远程代理；真正的外部降级交由 web_search（方案 3）。
        """
        domain = _domain_of(url)
        WEB_SCRAPE_FETCH_TOTAL.labels(source="httpx_retry", domain=domain).inc()
        return await self._fetch_via_jina(url, query="")

    async def _format_response(self, url: str, content: str, query: str = "") -> Dict[str, Any]:
        """格式化输出，防止撑爆大模型 Token 上限"""
        # 💡 移除常见的无用页脚与声明，进一步提纯文本
        content = re.sub(r"(?im)^.*(Copyright|版权所有)\s*[©©]?\s*20\d{2}.*$", "", content)
        content = re.sub(r"(?im)^.*(All Rights Reserved|保留所有权利).*$", "", content)
        # 💡 绝大部分免责声明位于文末，匹配到该标题后直接截断，丢弃后续全部万字废话
        content = re.sub(
            r"\n+\s*(免责声明|Disclaimer|投资风险提示)[：:\s].*", "", content, flags=re.IGNORECASE | re.DOTALL
        )

        # 💡 无条件持久化到 PGVector 知识库（修复：原实现仅在 query 非空时才入库，
        #    导致不带 query 的 fetch_webpage 调用永不写入，search_global_knowledge 永远查不到）。
        #    写入失败仅告警降级，不阻断正文返回。
        try:
            await asyncio.to_thread(self._persist_to_kb, content, url)
        except Exception as e:
            logger.warning("rag_persist_failed", url=url, error=str(e))

        # 带 query 时额外做语义检索，返回精准摘要；否则返回全文截断
        if query:
            try:
                summary = await asyncio.to_thread(self._retrieve_from_kb, content, query, url)
                if summary:
                    return {"status": "success", "data": {"url": url, "query": query, "content": summary}}
            except Exception as e:
                logger.warning("rag_extract_failed_fallback_fulltext", url=url, error=str(e))

        max_chars = 15000
        if len(content) > max_chars:
            # 💡 采用自适应安全截断，防止切断句子或 URL 导致大模型读取到破损语法
            content = safe_truncate(content, max_chars)

        content += "\n\n(💡 系统护栏提示：这是网页的原始内容。绝对禁止在你的输出中大段复制粘贴这些原文或打印整个 JSON/Markdown 结构！你必须消化后使用专业简练的语言进行总结。)"
        return {"status": "success", "data": {"url": url, "content": content}}

    def _split_docs(self, content: str) -> List:
        """RAG 切分：标题层级 + 滑动窗口，返回 LangChain Document 列表。"""
        try:
            from langchain_text_splitters import (  # type: ignore
                MarkdownHeaderTextSplitter,
                RecursiveCharacterTextSplitter,
            )
        except ImportError:
            return []

        # 1. 标题切分 (保留文档父子层级关系)
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ]
        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        md_splits = markdown_splitter.split_text(content)

        # 2. 长度滑动窗口切分 (优化：调大 chunk 尺寸保护财务表格，调整 \n 的优先级防止表格被从中间强行切断)
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2500,
            chunk_overlap=400,
            # 💡 核心优化：将句号优先级置于单换行符 \n 之前。
            # 财报 Markdown 表格按 \n 换行但通常没有句号，这样能最大程度保证普通段落按句子切分，大表格尽量作为一个整体，逼不得已时才按表行切分
            separators=["\n\n", "。", "！", "？", ".", "!", "?", "\n", "；", ";", "，", ",", " ", ""],
        )
        return text_splitter.split_documents(md_splits)

    def _persist_to_kb(self, content: str, url: str) -> bool:
        """无条件将网页碎片切分+向量化后幂等写入 PGVector 知识库。

        修复：原 _process_rag 仅在传入 query 时才入库，导致不带 query 的
        fetch_webpage 调用永不写入，search_global_knowledge 永远查不到。
        现抽出独立方法，由 _format_response 无条件调用。
        返回 True 表示入库成功；False/异常表示降级跳过（不阻断正文返回）。
        """
        try:
            splits = self._split_docs(content)
            if not splits:
                logger.warning("rag_persist_empty", url=url)
                return False

            from backend.core.config import settings
            from backend.core.embeddings import get_embeddings

            docs = []
            for s in splits:
                meta = s.metadata or {}
                headers = " > ".join([str(v) for k, v in meta.items() if str(k).startswith("Header")])
                # 把章节层级拼到正文前缀，保证检索命中时上下文完整
                prefix = f"[{headers}] " if headers else ""
                docs.append(prefix + s.page_content)

            vectors = get_embeddings(docs)
            if not vectors or len(vectors) != len(docs):
                # 零幻觉：embedding 不可用时降级，不假装已入库
                logger.warning("rag_persist_embedding_unavailable", url=url)
                return False

            url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
            current_ts = int(time.time())
            emb_version = settings.embedding_model

            from backend.core.database import SessionLocal
            from backend.core.models import WebpageKnowledgeBase

            rows = []
            for i, (doc, vec) in enumerate(zip(docs, vectors)):
                rows.append(
                    WebpageKnowledgeBase(
                        id=f"web_{url_hash}_{i}",
                        url=url,
                        content=doc,
                        timestamp=current_ts,
                        embedding_model_version=emb_version,
                        embedding=vec,
                    )
                )

            # 幂等写入：先按 id 删除旧片段 (同一 URL 重复抓取会更新而非堆积)
            with SessionLocal() as db:
                existing = {
                    r.id
                    for r in db.query(WebpageKnowledgeBase.id)
                    .filter(WebpageKnowledgeBase.id.in_([r.id for r in rows]))
                    .all()
                }
                if existing:
                    db.query(WebpageKnowledgeBase).filter(WebpageKnowledgeBase.id.in_(existing)).delete(
                        synchronize_session=False
                    )
                db.bulk_save_objects(rows)
                db.commit()
            logger.info("rag_persist_ok", url=url, chunks=len(rows))
            return True
        except Exception as e:
            logger.warning("rag_persist_failed", url=url, error=str(e))
            return False

    def _retrieve_from_kb(self, content: str, query: str, url: str) -> str:
        """基于 Query 从 PGVector 语义检索 Top3（限定当前 URL）。返回格式化摘要。"""
        try:
            splits = self._split_docs(content)
            if not splits:
                return "网页正文为空或无法切分。"

            from backend.core.embeddings import get_embeddings

            query_vec = get_embeddings([query])
            if not query_vec:
                return "⚠️ 查询向量生成失败，无法检索。\n\n网页开头：\n" + safe_truncate(content, 2000)

            from sqlalchemy import text as _text

            # 余弦距离: 1 - cosine_distance，按相似度降序取 Top3
            sql = _text(
                """
                SELECT content, url, 1 - (embedding <=> :q) AS score
                FROM webpage_knowledge_base
                WHERE url = :url
                ORDER BY embedding <=> :q
                LIMIT 3
                """
            )
            from backend.core.database import SessionLocal

            with SessionLocal() as db:
                res = db.execute(sql, {"q": str(query_vec[0]), "url": url}).fetchall()

            if not res:
                return "未能检索到与查询高度相关的段落。\n\n网页开头：\n" + safe_truncate(content, 2000)

            summary = f"🎯 根据您的问题 '{query}'，从该研报/网页中精准检索到以下相关内容：\n\n"
            for i, row in enumerate(res):
                doc = row[0]
                src = row[1]
                summary += f"[{i + 1}] 【无标题片段】\n{doc}\n(🔗 来源链接: {src})\n\n"

            summary += f"\n(💡 RAG 系统提示：1. 如果以上片段存在数据矛盾，请明确指出冲突并自行推断，严禁强行掩盖。 2. 绝对禁止在你的回答中大段复制粘贴或复述原始的 Markdown/JSON 内容，必须自行提炼核心结论！ 3. 在组织回答时，必须像学术论文一样，在你陈述的事实或数据后，严格使用对应的序号进行内联引用标注（例如：'苹果预计资本开支为150亿美元 [1] 。'），并在回答的最后附上「📚 参考文献」列表展示所有被引用的片段序号和对应标题。 4. 请务必在参考文献列表下方，单独附上该网页的原文链接：{url} ，以供用户点击阅读原文。)"
            return summary.strip()
        except Exception as e:
            logger.warning("rag_pg_failed_fallback", url=url, error=str(e))
            return "⚠️ 知识库检索异常。\n\n网页开头：\n" + safe_truncate(content, 2000)
