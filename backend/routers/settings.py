"""
系统设置 & 财报文件读取端点
从 main.py 迁出 (ARCH-01): settings/yfinance + financial-report
"""

import asyncio
import glob
import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.redis_client import l1_cached_redis

router = APIRouter(tags=["Settings"])


# ==========================================
# --- YFinance 兜底开关 ---
# ==========================================
class YFinanceToggle(BaseModel):
    enabled: bool


@router.post("/settings/yfinance")
async def toggle_yfinance(payload: YFinanceToggle):
    """前端一键控制 YFinance 兜底开关"""
    await l1_cached_redis.set("quant:settings:yfinance_enabled", "1" if payload.enabled else "0")
    return {
        "status": "success",
        "message": f"YFinance 兜底已{'开启' if payload.enabled else '关闭'}",
    }


@router.get("/settings/yfinance")
async def get_yfinance_setting():
    """获取 YFinance 当前开关状态"""
    val = await l1_cached_redis.get("quant:settings:yfinance_enabled")
    return {"status": "success", "enabled": val != "0"}


# ==========================================
# --- 本地财报文件读取 ---
# ==========================================
def _read_file_sync(target_file: str, ext: str) -> str:
    content = ""
    if ext in [".txt", ".md", ".csv"]:
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
    elif ext == ".pdf":
        import pdfplumber

        pages_content = []
        with pdfplumber.open(target_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                tables = page.extract_tables()
                if tables:
                    page_text += "\n\n[本页表格数据]:\n"
                    for table in tables:
                        for row in table:
                            clean_row = [str(cell).replace("\n", " ").strip() if cell else "" for cell in row]
                            page_text += " | ".join(clean_row) + "\n"
                        page_text += "\n"
                if page_text.strip():
                    pages_content.append(page_text)
        content = "\n".join(pages_content)
    return content


@router.get("/financial-report")
async def get_financial_report(ticker: str, chunk_index: int = 0):
    """读取 reports/ 目录下的本地财报文件"""
    if not ticker:
        raise HTTPException(status_code=400, detail="缺失股票代码参数")

    # 边界防御：防范目录穿越攻击
    safe_ticker = re.sub(r"[^A-Z0-9_.-]", "", ticker.upper()).replace("..", "")
    if not safe_ticker:
        raise HTTPException(status_code=400, detail="非法的股票代码参数")

    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "reports"))
    os.makedirs(reports_dir, exist_ok=True)
    search_pattern = os.path.join(reports_dir, f"*{safe_ticker}*.*")
    matched_files = glob.glob(search_pattern)

    if not matched_files:
        return {
            "status": "error",
            "message": f"未在财报目录下找到包含 {safe_ticker} 的财报文件。",
        }

    target_file = matched_files[0]
    ext = os.path.splitext(target_file)[1].lower()

    try:
        if ext not in [".txt", ".md", ".csv", ".pdf"]:
            return {"status": "error", "message": f"不支持的文件格式: {ext}。"}
        content = await asyncio.to_thread(_read_file_sync, target_file, ext)
        max_chars = 15000
        chunks = [content[i : i + max_chars] for i in range(0, len(content), max_chars)]
        if not chunks:
            return {"status": "error", "message": "文件内容提取为空。"}
        if chunk_index < 0 or chunk_index >= len(chunks):
            return {
                "status": "error",
                "message": f"chunk_index 越界。有效范围: 0 到 {len(chunks) - 1}",
            }

        return {
            "status": "success",
            "file_path": target_file,
            "total_chunks": len(chunks),
            "current_chunk_index": chunk_index,
            "content": chunks[chunk_index],
            "message": f"成功读取财报文件第 {chunk_index + 1}/{len(chunks)} 部分。",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
