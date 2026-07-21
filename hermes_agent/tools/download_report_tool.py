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
    # ── 港股 ──
    "hkexnews.hk",
    "www1.hkexnews.hk",
    "hkex.com.hk",          # 港交所官网
    "www.hkex.com.hk",
    "news.hkex.com.hk",
    # ── 美股 (SEC + IR 托管平台) ──
    "sec.gov",
    "www.sec.gov",
    "q4cdn.com",            # Q4 Inc — Apple/NVIDIA/Meta 等公司 IR 文件托管
    "s2.q4cdn.com",
    "ir.yuewen.com",
    "yuewen.com",
    "apple.com",            # Apple Investor Relations
    "investor.apple.com",
    "microsoft.com",        # Microsoft IR
    "s203.q4cdn.com",       # 各公司专属 q4cdn 子域
    "edgar-online.com",
    # ── A股 ──
    "cninfo.com.cn",        # 巨潮资讯 (深交所指定披露平台)
    "static.cninfo.com.cn",
    "sse.com.cn",           # 上交所
    "static.sse.com.cn",
    "szse.cn",              # 深交所
    "eastmoney.com",        # 东方财富
    "sina.com.cn",
    "finance.sina.com.cn",
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


# 报告类型映射（标准化文件名中的类型段）
_REPORT_TYPES = {
    "annual": "annual_report",
    "年报": "annual_report",
    "interim": "interim_report",
    "中报": "interim_report",
    "半年报": "interim_report",
    "quarterly": "quarterly_report",
    "季报": "quarterly_report",
    "announcement": "announcement",
    "公告": "announcement",
    "research": "research_note",
    "研报": "research_note",
    "presentation": "presentation",
    "演示": "presentation",
}


def _normalize_ticker_for_filename(ticker: str) -> str:
    """
    将各种格式的 ticker 统一为文件名安全格式，保留 '.' 以兼容后端 glob 匹配。

    输入 → 输出:
      "0772.HK" / "HK.0772" / "0772" → "0772.HK"
      "AAPL" / "US.AAPL"            → "AAPL"
      "600519.SH" / "SH.600519"     → "600519.SH"
    """
    t = ticker.upper().strip()

    # 已经是 "CODE.MARKET" 格式 (如 0772.HK, 600519.SH)
    if re.match(r"^\d+\.\w+$", t):
        return t

    # "MARKET.CODE" 格式 (如 HK.0772, US.AAPL, SH.600519) → 翻转为 CODE.MARKET
    m = re.match(r"^(HK|US|SH|SZ)\.(.+)$", t)
    if m:
        market, code = m.group(1), m.group(2)
        # 美股不需要后缀 (AAPL 而非 AAPL.US)
        if market == "US":
            return code
        return f"{code}.{market}"

    # 纯数字推断市场
    if t.isdigit():
        if len(t) == 4 or len(t) == 5:
            return f"{t.zfill(4)}.HK"
        if len(t) == 6:
            suffix = "SH" if t.startswith(("60", "68")) else "SZ"
            return f"{t}.{suffix}"

    # 其他情况原样返回 (如 AAPL, TSLA)
    return re.sub(r"[^\w.\-]", "_", t)


def _build_filename(ticker: str, url: str, report_type: str = "", year: str = "", custom_name: str = "") -> str:
    """
    生成标准化文件名，确保包含 ticker 以兼容后端 glob `*{ticker}*.*` 匹配。

    命名规范: {TICKER}_{report_type}_{year}.{ext}
    示例:
      0772.HK_annual_report_2025.pdf
      AAPL_interim_report_2025.pdf
      600519.SH_announcement_2025.pdf
    """
    safe_ticker = _normalize_ticker_for_filename(ticker)

    # 确定扩展名
    url_filename = url.rstrip("/").split("/")[-1]
    ext = Path(url_filename).suffix.lower() if Path(url_filename).suffix else ".pdf"
    if ext not in (".pdf", ".txt", ".md", ".csv"):
        ext = ".pdf"

    # 如果用户提供了自定义文件名，确保 ticker 前缀存在
    if custom_name:
        name = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", custom_name)
        # 确保 ticker 在文件名中（后端匹配依赖）
        if safe_ticker not in name:
            name = f"{safe_ticker}_{name}"
        if not name.endswith(ext):
            name += ext
        return name

    # 标准化命名: {TICKER}_{type}_{year}{ext}
    type_key = _REPORT_TYPES.get(report_type.lower(), "") if report_type else ""
    parts = [safe_ticker]
    if type_key:
        parts.append(type_key)
    elif report_type:
        # 未识别的类型，清理后直接使用
        parts.append(re.sub(r"[^\w\-]", "_", report_type.lower()))
    if year and re.match(r"^\d{4}$", year):
        parts.append(year)

    # 如果只有 ticker 没有额外信息，从 URL 文件名补充
    if len(parts) == 1:
        url_stem = Path(url_filename).stem
        if url_stem and len(url_stem) > 3:
            parts.append(re.sub(r"[^\w\-]", "_", url_stem))
        else:
            parts.append("report")

    return "_".join(parts) + ext


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
                "description": "股票代码，用于命名本地文件并确保后续可被 analyze_financial_report 匹配。例如 0772.HK、AAPL、600519",
            },
            "report_type": {
                "type": "string",
                "description": "报告类型，用于标准化命名。可选值: annual(年报), interim(中报), quarterly(季报), announcement(公告), research(研报), presentation(演示)",
            },
            "year": {
                "type": "string",
                "description": "报告对应年份，例如 2025",
            },
            "filename": {
                "type": "string",
                "description": "可选：自定义保存文件名（不含路径）。即使指定自定义名，系统也会确保文件名中包含 ticker 以便后续查找。",
            },
        },
        "required": ["url", "ticker"],
    }

    async def run(self, url: str, ticker: str = "", report_type: str = "", year: str = "", filename: str = "") -> Dict[str, Any]:
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

        # 3. 生成标准化文件名（确保包含 ticker）
        safe_name = _build_filename(
            ticker=ticker,
            url=url,
            report_type=report_type,
            year=year,
            custom_name=filename,
        )

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
            # SEC.gov 要求声明性 User-Agent（公司名+邮箱），否则触发 Cloudflare 403
            # 参考: https://www.sec.gov/os/accessing-edgar-data
            if "sec.gov" in url:
                headers = {
                    "User-Agent": "QuantAgent Research research@quant-agent.dev",
                    "Accept-Encoding": "gzip, deflate",
                    "Accept": "application/pdf,*/*",
                    "Host": "www.sec.gov",
                }
            else:
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
