"""DataSource Legacy adapters package (BE-ARCH-04).

统一注册入口: ensure_all_datasources_registered()
  - 应用启动时由 bootstrap/lifecycle.py 调用一次
  - 幂等：重复调用安全（各 ensure_* 内部判重）
  - Facade 经 DataSourceRegistry 选源，所有适配器必须提前注册
"""

from __future__ import annotations

from backend.core.logger import logger


def ensure_all_datasources_registered() -> list[str]:
    """幂等注册全部数据源适配器到 DataSourceRegistry。

    注册顺序即业务权重参考（实际选源由 Facade _business_weight 决定）。
    返回已成功注册的源名称列表。
    """
    registered: list[str] = []

    # ── 核心行情源 ──
    try:
        from backend.services.datasource.adapters.futu import ensure_futu_registered

        name = ensure_futu_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] Futu 注册失败: {e}")

    try:
        from backend.services.datasource.adapters.legacy_yfinance import ensure_yfinance_registered

        name = ensure_yfinance_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] YFinance 注册失败: {e}")

    try:
        from backend.services.datasource.adapters.finnhub import ensure_finnhub_registered

        name = ensure_finnhub_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] Finnhub 注册失败: {e}")

    try:
        from backend.services.datasource.adapters.fmp import ensure_fmp_registered

        name = ensure_fmp_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] FMP 注册失败: {e}")

    # ── A 股 / 宏观源 ──
    try:
        from backend.services.datasource.adapters.akshare import ensure_akshare_registered

        name = ensure_akshare_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] AKShare 注册失败: {e}")

    try:
        # 💡 FIX-276: 改用远程适配器 (adapters/tushare.py), 与 akshare 对称。
        # 原 backend.services.tushare.adapter 为本地 SDK 模式, 主节点无 tushare 包时
        # is_available()=False 跳过注册, 导致看板 list_names() 不含 tushare、健康度看板不显示。
        # 远程模式无条件注册, 使看板始终感知 tushare_remote 节点 (即使今日无流量)。
        from backend.services.datasource.adapters.tushare import ensure_tushare_registered

        name = ensure_tushare_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] Tushare 注册失败: {e}")

    # ── 宏观数据源 (FRED / DBnomics / RBI) ──
    try:
        from backend.services.datasource.adapters.macro import ensure_macro_sources_registered

        names = ensure_macro_sources_registered()
        registered.extend(names)
    except Exception as e:
        logger.warning(f"[Registry] 宏观数据源注册失败: {e}")

    # ── 搜索 / 抓取源 ──
    try:
        from backend.services.datasource.adapters.search import ensure_search_sources_registered

        names = ensure_search_sources_registered()
        registered.extend(names)
    except Exception as e:
        logger.warning(f"[Registry] 搜索数据源注册失败: {e}")

    # ── 散户情绪源 (Sentiment / ApeWisdom, 远程) ──
    try:
        from backend.services.datasource.adapters.sentiment import ensure_sentiment_registered

        name = ensure_sentiment_registered()
        if name:
            registered.append(name)
    except Exception as e:
        logger.warning(f"[Registry] Sentiment 注册失败: {e}")

    logger.info(f"[Registry] 数据源适配器注册完成: {registered}")
    return registered
