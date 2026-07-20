"""
download_report — 在线财报/研报 PDF 下载工具
=============================================

从公开 URL (港交所披露易、公司 IR 页面、SEC EDGAR 等) 下载 PDF/文件到本地 reports/ 目录，
供 analyze_financial_report 工具后续解析。

典型工作流:
  1. web_search("阅文集团 0772 年报 site:hkexnews.hk") → 获取 PDF 链接
  2. download_report(url=..., ticker="0772.HK") → 下载到 reports/
  3. analyze_financial_report(ticker="0772.HK") → 解析内容
"""

import re
from pathlib import Path
from typing import Any, Dict

import httpx

from hermes_agent.tool_registry import register_tool

from .base import BaseTool

# reports 目录：项目根目录下
_REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"

# 允许下载的域名白名单（防止 SSRF）
_ALLOWED_DOMAINS = [
    "hkexnews.hk",
    "www1.hkexnews.hk",
    "sec.gov",
    "www.sec.gov",
    "ir.yuewen.com",
    "yuewen.com",
    "eastmoney.com",
    "sina.com.cn",
    "finance.sina.com.cn",
    "cninfo.com.cn",
    "sse.com.cn",
    "szse.cn",
]

# 最大下载大小 50MB（年报 PDF 通常 5-20MB）
_MAX_FILE_SIZE = 50 * 1024 * 1024

# 下载超时
_DOWNLOAD_TIMEOUT = 120.0


def _is_allowed_url(url: str) -> bool:
    """校验 URL 是否在白名单域名内"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return any(hostname == d or hostname.endswith(f".{d}") for d in _ALLOWED_DOMAINS)


def _sanitize_filename(ticker: str, url: str) -> str:
    """生成安全的本地文件名"""
    # 从 URL 提取原始文件名
    url_filename = url.rstrip("/").split("/")[-1]

    # 清理 ticker 中的特殊字符
    safe_ticker = re.sub(r"[^\w.\-]", "_", ticker.upper())

    if url_filename.endswith(".pdf"):
        return f"{safe_ticker}_{url_filename}"
    else:
        # 非 PDF 也保留扩展名
        ext = Path(url_filename).suffix or ".pdf"
        return f"{safe_ticker}_report{ext}"


@register_tool
class DownloadReportTool(BaseTool):
    """
    从公开 URL 下载财报/研报 PDF 到本地 reports/ 目录。
    """

    name = "download_report"
    description = (
        "从公开 URL 下载财报或研报 PDF 文件到本地 reports/ 目录。"
        "典型用法：先用 web_search 搜索港交所披露易或 SEC 的 PDF 链接，"
        "再调用本工具下载，最后用 analyze_financial_report 解析内容。"
        "支持域名：hkexnews.hk、sec.gov、cninfo.com.cn、公司 IR 页面等。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "PDF 文件的完整下载链接，例如 https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0422/2026042200668.pdf",
            },
            "ticker": {
                "type": "string",
                "description": "股票代码，用于命名本地文件，例如 0772.HK、AAPL",
            },
            "filename": {
                "type": "string",
                "description": "可选：自定义保存文件名（不含路径），例如 0772_HK_2025_annual_report.pdf",
            },
        },
        "required": ["url", "ticker"],
    }

    async def run(self, url: str, ticker: str = "", filename: str = "") -> Dict[str, Any]:
        if not url:
            return {"status": "error", "message": "缺失 url 参数。"}
        if not ticker:
            return {"status": "error", "message": "缺失 ticker 参数。"}

        # 1. 安全校验：域名白名单
        if not _is_allowed_url(url):
            return {
                "status": "error",
                "message": f"不允许从该域名下载。支持的域名: {', '.join(_ALLOWED_DOMAINS[:6])}...",
            }

        # 2. 确保 reports 目录存在
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # 3. 确定文件名
        if filename:
            safe_name = re.sub(r"[^\w.\-]", "_", filename)
        else:
            safe_name = _sanitize_filename(ticker, url)

        filepath = _REPORTS_DIR / safe_name

        # 4. 如果文件已存在且非空，直接返回（避免重复下载）
        if filepath.exists() and filepath.stat().st_size > 0:
            return {
                "status": "success",
                "message": f"文件已存在，无需重复下载。",
                "file_path": str(filepath),
                "file_size_mb": round(filepath.stat().st_size / 1024 / 1024, 2),
            }

        # 5. 下载文件
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/pdf,*/*",
            }

            async with httpx.AsyncClient(
                timeout=_DOWNLOAD_TIMEOUT,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)

                if resp.status_code != 200:
                    return {
                        "status": "error",
                        "message": f"下载失败: HTTP {resp.status_code}。该链接可能有 Cloudflare 防护或已过期。",
                    }

                content = resp.content

                # 校验大小
                if len(content) > _MAX_FILE_SIZE:
                    return {
                        "status": "error",
                        "message": f"文件过大 ({len(content) / 1024 / 1024:.1f}MB)，超过 50MB 限制。",
                    }

                # 校验是否为有效 PDF（魔数检查）
                if not content[:4] == b"%PDF":
                    # 可能是 HTML 错误页面（Cloudflare challenge）
                    if b"<html" in content[:500].lower():
                        return {
                            "status": "error",
                            "message": "下载内容为 HTML 页面而非 PDF，可能触发了 Cloudflare 防护。建议手动在浏览器中下载后放入 reports/ 目录。",
                        }

                # 写入文件
                filepath.write_bytes(content)

                return {
                    "status": "success",
                    "message": f"下载完成，已保存至 reports/{safe_name}",
                    "file_path": str(filepath),
                    "file_size_mb": round(len(content) / 1024 / 1024, 2),
                    "next_step": f"现在可以调用 analyze_financial_report(ticker=\"{ticker}\") 解析该文件。",
                }

        except httpx.TimeoutException:
            return {
                "status": "error",
                "message": f"下载超时 ({_DOWNLOAD_TIMEOUT:.0f}s)。文件可能较大或网络不稳定，建议手动下载。",
            }
        except Exception as e:
            return {"status": "error", "message": f"下载异常: {str(e)}"}
