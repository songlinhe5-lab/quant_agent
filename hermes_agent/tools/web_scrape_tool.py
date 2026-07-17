import asyncio
import hashlib
import os
import re
import time
from typing import Any, Dict

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.middleware import httpx_log_request, httpx_log_response
from backend.core.utils import safe_truncate
from hermes_agent.tool_registry import register_tool

from .base import BaseTool


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
            "query": {"type": "string", "description": "可选：由于网页可能极长，强烈建议提供此参数以触发 RAG 语义检索。请务必输入极其具体的问题或事实细节（例如：'高管对下个季度的营收和毛利率指引是多少？' 或 '该研报提到的三大看多逻辑和目标价'）。严禁输入诸如'总结'、'财报'、'核心内容'等宽泛废话。"}
        },
        "required": ["url"]
    }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def run(self, url: str, query: str = "") -> Dict[str, Any]:
        if not url:
            return {"status": "error", "message": "URL 不能为空"}

        # 💡 安全防线：防范 SSRF 与本地文件读取 (Local File Inclusion) 漏洞
        # 如果不限制 scheme，黑客可以通过 Prompt 注入让无头浏览器读取 file:///etc/passwd 或 file:///app/.env
        if not url.lower().startswith(("http://", "https://")):
            return {"status": "error", "message": "非法的 URL 协议。出于安全风控原因，仅允许访问 http(s) 标准网页。"}

        # 使用 Jina Reader API，免费且专门为大模型优化的网页转 Markdown 接口
        jina_url = f"https://r.jina.ai/{url}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, event_hooks={'request': [httpx_log_request], 'response': [httpx_log_response]}) as client:
                resp = await client.get(jina_url, headers=headers)
                resp.raise_for_status()
                content = resp.text

                # 💡 利用正则清洗 Markdown 中的冗余图片和超链接，极大节省大模型 Token
                content = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', content)  # 完全移除图片及图片链接
                content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)  # 超链接“剥壳”：仅保留链接文字，移除 URL

                # 💡 拦截动态反爬与 JS 护盾：如果字数过少或包含反爬特征，主动抛出异常走降级
                if len(content) < 200 or "Please enable JS" in content or "访问受限" in content or "Just a moment" in content:
                    raise ValueError("触发目标网站反爬屏蔽或遇到了 SPA 动态渲染页")

                return await self._format_response(url, content, query)
        except Exception as e:
            print(f"⚠️ [WebScrape] Jina API 提取受阻 ({repr(e)})，正在唤起本地无头浏览器兜底...")
            return await self._scrape_with_browser(url, query)

    async def _format_response(self, url: str, content: str, query: str = "") -> Dict[str, Any]:
        """格式化输出，防止撑爆大模型 Token 上限"""
        # 💡 移除常见的无用页脚与声明，进一步提纯文本
        content = re.sub(r'(?im)^.*(Copyright|版权所有)\s*[©©]?\s*20\d{2}.*$', '', content)
        content = re.sub(r'(?im)^.*(All Rights Reserved|保留所有权利).*$', '', content)
        # 💡 绝大部分免责声明位于文末，匹配到该标题后直接截断，丢弃后续全部万字废话
        content = re.sub(r'\n+\s*(免责声明|Disclaimer|投资风险提示)[：:\s].*', '', content, flags=re.IGNORECASE | re.DOTALL)

        if query:
            try:
                summary = await asyncio.to_thread(self._process_rag, content, query, url)
                return {"status": "success", "data": {"url": url, "query": query, "content": summary}}
            except Exception as e:
                print(f"⚠️ [WebScrape] RAG 提取失败: {e}，将降级为全文截断返回。")

        max_chars = 15000
        if len(content) > max_chars:
            # 💡 采用自适应安全截断，防止切断句子或 URL 导致大模型读取到破损语法
            content = safe_truncate(content, max_chars)

        content += "\n\n(💡 系统护栏提示：这是网页的原始内容。绝对禁止在你的输出中大段复制粘贴这些原文或打印整个 JSON/Markdown 结构！你必须消化后使用专业简练的语言进行总结。)"
        return {"status": "success", "data": {"url": url, "content": content}}

    async def _scrape_with_browser(self, url: str, query: str) -> Dict[str, Any]:
        """自建 DrissionPage 无头浏览器降级提取 (对抗动态 JS 与高强度反爬)"""
        try:
            from DrissionPage import ChromiumOptions, ChromiumPage  # type: ignore
        except ImportError:
            return {"status": "error", "message": "当前环境未安装 DrissionPage。请在终端执行: pip install DrissionPage"}

        try:
            # 💡 增加显式的 -> str 类型注解，消除 Pylance 将其误判为 MethodType 的报错
            def _scrape() -> str:
                import time

                co = ChromiumOptions()

                # 💡 挂载本地 Chrome 用户数据目录，继承真实登录态和 Cookie 突破付费墙 (Paywall)
                user_data_dir = os.getenv("CHROME_USER_DATA_DIR")
                if user_data_dir:
                    co.set_user_data_path(user_data_dir)

                # 💡 放弃传统的 co.headless()，改用 Chrome 最新的 --headless=new 模式
                # 它使用的是真实的浏览器渲染管线，极难被网站的风控系统（如 Cloudflare）识别
                co.set_argument('--headless=new')
                co.set_argument('--disable-blink-features=AutomationControlled') # 隐藏 WebDriver 特征
                co.set_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

                page = ChromiumPage(addr_or_opts=co)
                try:
                    page.get(url, retry=2, timeout=30)
                    time.sleep(3)  # 留出 3 秒等待页面的 JS、AJAX 请求和 Vue/React 组件完全挂载

                    # 提取 <body> 下的所有纯文本 (自动屏蔽 HTML 和脚本标签，等效于 innerText)
                    body = page.ele('tag:body')
                    # 💡 增加显式的 str() 强转保护
                    return str(body.text) if body else ""
                finally:
                    page.quit()

            # DrissionPage 核心为同步，必须通过 asyncio.to_thread 防止阻塞 FastAPI 主事件循环
            content = await asyncio.to_thread(_scrape)

            if not content or len(content.strip()) < 50:
                return {"status": "error", "message": "无头浏览器提取的内容为空，对方网站可能存在极强的风控系统。"}

            return await self._format_response(url, content.strip(), query)
        except Exception as e:
            return {"status": "error", "message": f"无头浏览器渲染失败: {str(e)}"}

    def _process_rag(self, content: str, query: str, url: str) -> str:
        """执行本地 RAG 切分与检索"""
        try:
            import chromadb
            from chromadb.utils import embedding_functions
            from langchain_text_splitters import (  # type: ignore
                MarkdownHeaderTextSplitter,
                RecursiveCharacterTextSplitter,
            )
        except ImportError:
            return "⚠️ 缺少 langchain-text-splitters 或 chromadb 依赖，无法进行 RAG 检索。\n\n" + safe_truncate(content, 5000)

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
            separators=["\n\n", "。", "！", "？", ".", "!", "?", "\n", "；", ";", "，", ",", " ", ""]
        )
        splits = text_splitter.split_documents(md_splits)

        if not splits:
            return "网页正文为空或无法切分。"

        # 3. 构建持久化级别的向量数据库 (存入本地 data/chroma_db 目录)
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "chroma_db"))
        client = chromadb.PersistentClient(path=db_path)

        emb_api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        if emb_api_key:
            emb_base_url = os.getenv("EMBEDDING_BASE_URL")
            emb_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            emb_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=emb_api_key,
                model_name=emb_model,
                api_base=emb_base_url
            )
        else:
            emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="paraphrase-multilingual-MiniLM-L12-v2")

        # 💡 使用 get_or_create_collection 建立长效独立的网页知识库 Collection
        collection = client.get_or_create_collection(name="webpage_knowledge_base", embedding_function=emb_fn)  # type: ignore

        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        current_ts = int(time.time())
        docs = [s.page_content for s in splits]
        metadatas = [{**(s.metadata if s.metadata else {"source": "webpage"}), "url": url, "length": len(s.page_content), "timestamp": current_ts} for s in splits]
        ids = [f"web_{url_hash}_{i}" for i in range(len(splits))]

        # 💡 修复：分批与指数退避重试，防范第三方 Embedding API 单次输入越界与并发限流
        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=2, max=10), reraise=True)
        def _upsert_with_retry(b_docs, b_metas, b_ids):
            collection.upsert(documents=b_docs, metadatas=b_metas, ids=b_ids)  # type: ignore

        batch_size = 60
        for i in range(0, len(docs), batch_size):
            _upsert_with_retry(
                docs[i:i+batch_size],
                metadatas[i:i+batch_size],
                ids[i:i+batch_size]
            )

        # 4. 根据 Query 语义检索 Top 3 最相关片段
        results = collection.query(query_texts=[query], n_results=min(3, len(splits)))

        docs = results.get("documents")
        metas = results.get("metadatas")

        if not docs or not docs[0]:
            return "未能检索到与查询高度相关的段落。\n\n网页开头：\n" + safe_truncate(content, 2000)

        summary = f"🎯 根据您的问题 '{query}'，从该研报/网页中精准检索到以下相关内容：\n\n"

        safe_metas = metas[0] if metas and metas[0] else [{}] * len(docs[0])

        for i, (doc, meta) in enumerate(zip(docs[0], safe_metas)):
            meta = meta or {}
            headers = " > ".join([str(v) for k, v in meta.items() if str(k).startswith("Header")])
            title = f"[{i+1}] 【章节: {headers}】" if headers else f"[{i+1}] 【无标题片段】"
            summary += f"{title}\n{doc}\n\n"

        summary += f"\n(💡 RAG 系统提示：1. 如果以上片段存在数据矛盾，请明确指出冲突并自行推断，严禁强行掩盖。 2. 绝对禁止在你的回答中大段复制粘贴或复述原始的 Markdown/JSON 内容，必须自行提炼核心结论！ 3. 在组织回答时，必须像学术论文一样，在你陈述的事实或数据后，严格使用对应的序号进行内联引用标注（例如：'苹果预计资本开支为150亿美元 [1] 。'），并在回答的最后附上「📚 参考文献」列表展示所有被引用的片段序号和对应标题。 4. 请务必在参考文献列表下方，单独附上该网页的原文链接：{url} ，以供用户点击阅读原文。)"
        return summary.strip()
