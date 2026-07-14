"""
Ticker 格式化纯函数（BE-ARCH-01）

从具体数据源包抽出，供 Router / Application 使用，避免 routers 依赖 futu/yfinance 包。
"""


def format_ticker(ticker: str) -> str:
    """格式化 ticker 为 Futu 标准格式。"""
    ticker = ticker.upper()
    index_map = {
        "HSI": "HK.800000",
        "HSTECH": "HK.800700",
        "SPX": "US.SPX",
        "NDX": "US.NDX",
        "TSMC": "US.TSM",
        "US.TSMC": "US.TSM",
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

    if any(
        ticker.startswith(prefix)
        for prefix in ["US.", "SH.", "SZ.", "JP.", "SG.", "UK.", "LSE."]
    ):
        return ticker

    return f"US.{ticker}"


def format_yf_ticker(ticker: str) -> str:
    """格式化 ticker 为 Yahoo Finance 符号（与 yfinance_service 行为对齐）。"""
    yf_ticker = ticker.upper().replace("US.", "")
    index_map = {
        "HSI": "^HSI",
        "HK.800000": "^HSI",
        "HK.HSI": "^HSI",
        "HSTECH": "^HSTECH",
        "HK.800700": "^HSTECH",
        "SPX": "^GSPC",
        "IXIC": "^IXIC",
        "DJI": "^DJI",
        "VIX": "^VIX",
        "SSEC": "000001.SS",
        "000001.SH": "000001.SS",
        "CSI300": "000300.SS",
        "399300.SZ": "399300.SZ",
        "399001.SZ": "399001.SZ",
        "TSMC": "TSM",
        "N225": "^N225",
        "DX-Y": "DX-Y.NYB",
        "TNX": "^TNX",
        "GC=F": "GC=F",
        "JGB10Y": "^JN09T",
        "USDCNH": "USDCNH=X",
        "CNH=X": "USDCNH=X",
        "BTC": "BTC-USD",
        "CL=F": "CL=F",
    }
    if yf_ticker in index_map:
        return index_map[yf_ticker]

    if yf_ticker.endswith(".HK") or yf_ticker.startswith("HK."):
        code = yf_ticker.replace(".HK", "").replace("HK.", "")
        yf_ticker = (
            f"{code.lstrip('0').zfill(4)}.HK" if code.isdigit() else f"{code}.HK"
        )
    elif yf_ticker.startswith("SH."):
        yf_ticker = yf_ticker.replace("SH.", "") + ".SS"
    elif yf_ticker.endswith(".SH"):
        yf_ticker = yf_ticker.replace(".SH", ".SS")
    elif yf_ticker.startswith("SZ."):
        yf_ticker = yf_ticker.replace("SZ.", "") + ".SZ"
    elif yf_ticker.startswith("JP."):
        yf_ticker = yf_ticker.replace("JP.", "") + ".T"
    elif yf_ticker.startswith("SG."):
        yf_ticker = yf_ticker.replace("SG.", "") + ".SI"
    elif yf_ticker.startswith("UK.") or yf_ticker.startswith("LSE."):
        yf_ticker = yf_ticker.replace("UK.", "").replace("LSE.", "") + ".L"

    return yf_ticker
