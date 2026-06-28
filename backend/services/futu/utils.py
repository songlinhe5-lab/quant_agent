"""
Futu 工具函数模块
提供通用的 ticker 格式化和判断工具
"""


def is_futu_unsupported(ticker: str) -> bool:
    """快速判断是否为富途原生不支持的大类资产（外汇、加密货币、特殊宏观商品等）"""
    t = ticker.upper()
    # 带有这些符号的通常是雅虎专用的外汇、加密货币、期指等
    if "=" in t or "-" in t or "^" in t:
        return True
    if t in ["DX-Y.NYB", "DGS10", "GC=F", "CL=F", "HG=F"]:
        return True
    return False


def format_ticker(ticker: str) -> str:
    """格式化 ticker 为 Futu 标准格式"""
    ticker = ticker.upper()
    index_map = {
        "HSI": "HK.800000",
        "HSTECH": "HK.800700",
        "SPX": "US.SPX",
        "NDX": "US.NDX",
        "TSMC": "US.TSM",
        "US.TSMC": "US.TSM"  # 智能纠正用户的惯用称呼
    }
    if ticker in index_map:
        return index_map[ticker]

    if ticker.endswith(".HK") or ticker.startswith("HK."):
        code = ticker.replace(".HK", "").replace("HK.", "")
        return f"HK.{code.zfill(5) if code.isdigit() else code}"

    if ticker.endswith(".SH") or ticker.endswith(".SS"):
        return f"SH.{ticker.replace('.SH', '').replace('.SS', '')}"
    if ticker.endswith(".SZ"):
        return f"SZ.{ticker.replace('.SZ', '')}"
    if ticker.endswith(".US"):
        return f"US.{ticker.replace('.US', '')}"

    if any(ticker.startswith(prefix) for prefix in ["US.", "SH.", "SZ.", "JP.", "SG.", "UK.", "LSE."]):  # noqa: E501
        return ticker

    return f"US.{ticker}"
