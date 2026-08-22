"""
Futu 行情数据处理模块
负责实时行情、历史K线、盘口深度等行情相关功能
"""

import asyncio
import time
from typing import Any, Dict

import pandas as pd
from futu import RET_OK, AuType, KLType, SubType

from data_subservice._internal.logger import logger
from data_subservice._internal.retry_utils import with_global_retry

from ._compat import safe_float
from .cache_manager import _SEARCH_QUOTE_TTL, CacheManager


def _map_heat_market(market: str) -> Any:
    """把前端/主服务传的市场代码映射到 futu Market 枚举。

    ⚠️ 关键：前端用 'A'/'CN' 表示沪深A股。实测 futu 10.10 Market 枚举
    成员为 AU/CA/CC/EC/FX/HK/HK_FUTURE/JP/MY/NONE/SG/SH/SZ/US, **没有 CN**。
    A股对应 Market.SH(沪)/Market.SZ(深), 因此 'A' 映射到 Market.SH(沪市 A 股板块)。
    此前用 getattr(Market, 'A', Market.HK) 会 fallback 到港股,
    导致 A 股热力图拿到港股数据甚至为空。
    """
    from futu import Market

    key = market.upper()
    if key in ("A", "CN", "CNSH", "SH"):
        return Market.SH
    if key == "SZ":
        return Market.SZ
    if key in ("HK", "US", "SG", "JP", "AU", "CA"):
        return getattr(Market, key, Market.HK)
    # 其他未知市场 fallback 到 HK（保持向后兼容）
    return Market.HK


async def _execute_unsubscriptions(conn_mgr, cache_mgr: CacheManager, evicted: list) -> None:
    """
    执行 LRU 淘汰后的实际退订操作。
    按 ticker 分组批量退订，避免频繁调用 OpenD API。
    """
    if not evicted:
        return

    # 按 ticker 分组: {ticker: [sub_type_str, ...]}
    ticker_groups: dict = {}
    for ticker, sub_type_str in evicted:
        ticker_groups.setdefault(ticker, []).append(sub_type_str)

    for ticker, sub_types in ticker_groups.items():
        try:
            # 将字符串转回 SubType 枚举
            futu_sub_types = [getattr(SubType, st, None) for st in sub_types]
            futu_sub_types = [s for s in futu_sub_types if s is not None]
            if not futu_sub_types:
                continue

            ret, _ = await asyncio.to_thread(conn_mgr.quote_ctx.unsubscribe, [ticker], futu_sub_types)
            if ret == RET_OK:
                for st in sub_types:
                    cache_mgr.remove_topic(ticker, st)
                logger.info(f"[Futu LRU] 退订 {ticker} {sub_types}")
            else:
                logger.warning(f"[Futu LRU] 退订失败 {ticker}: {ret}")
        except Exception as e:
            logger.warning(f"[Futu LRU] 退订异常 {ticker}: {e}")


class QuoteHandler:
    """行情数据处理器"""

    def __init__(self, connection_manager, cache_manager: CacheManager):
        self.conn_mgr = connection_manager
        self.cache_mgr = cache_manager

    @with_global_retry
    async def get_quote(self, ticker: str, format_ticker_func, is_unsupported_func) -> Dict[str, Any]:  # noqa: E501
        """获取实时行情（带L1缓存）"""
        if is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker)

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_quote(market_ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # L1 极速内存缓存 (TTL: 3秒)
        now = time.time()
        cached = self.cache_mgr.get_quote_cache(market_ticker)
        if cached and now - cached[0] < 3.0:
            return cached[1]

        if not self.cache_mgr.has_topic(market_ticker, SubType.QUOTE):
            # LRU 容量检查：超限时淘汰最久未用的订阅
            evicted = self.cache_mgr.ensure_capacity(needed=2)  # 💡 需要2个槽位：QUOTE + ORDER_BOOK
            await _execute_unsubscriptions(self.conn_mgr, self.cache_mgr, evicted)

            # 💡 同时订阅报价和盘口深度，确保 Level 2 DOM 数据实时推送
            ret, msg = self.conn_mgr.quote_ctx.subscribe(
                [market_ticker],
                [SubType.QUOTE, SubType.ORDER_BOOK],
                subscribe_push=True,  # 开启推送，实时报价 + 盘口深度通过 PushHandler 桥接到 Redis
                extended_time=True,  # noqa: E501
            )
            if ret != RET_OK:
                return {"status": "error", "message": msg}
            self.cache_mgr.touch_topic(market_ticker, SubType.QUOTE)
            self.cache_mgr.touch_topic(market_ticker, SubType.ORDER_BOOK)

        ret, df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_stock_quote, [market_ticker])
        if ret != RET_OK or not isinstance(df, pd.DataFrame) or df.empty:
            return {"status": "error", "message": f"行情获取失败: {df}"}

        result = self.cache_mgr.compress_quote_data(df.iloc[0])
        self.cache_mgr.set_quote_cache(market_ticker, now, result)
        return result

    @with_global_retry
    async def get_search_news(self, ticker: str, max_count: int = 10) -> Dict[str, Any]:
        """按关键词搜索资讯（港股/美股个股新闻，Futu 富途资讯 + 交易所公告 + 评级）。

        Futu ``get_search_news(keyword)`` 按关键词返回新闻/公告/评级，含 ``related_securities``
        关联标的列表（如 ``HK.00772``）。对港股 ticker，用股票代码作为关键词搜索，
        并按 ``related_securities`` 过滤出真正关联该标的的资讯，避免混入无关结果。
        """
        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # 从 ticker 提取搜索关键词：HK.00772 -> 00772; 00700.HK -> 00700
        code = str(ticker).replace("HK.", "").replace("US.", "").replace(".HK", "").replace(".US", "").strip()
        if not code:
            return {"status": "error", "message": "无效 ticker"}
        # 港股代码补零到5位（Futu 用 00700 这类5位码）：0772 -> 00772
        if code.isdigit() and (ticker.startswith("HK.") or ticker.endswith(".HK")):
            code = code.zfill(5)

        try:
            ret, df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_search_news, code, max_count)
        except Exception as e:
            logger.warning(f"[Futu] get_search_news 异常 {ticker}: {e}")
            return {"status": "error", "message": f"资讯获取失败: {e}"}

        if ret != RET_OK or not isinstance(df, pd.DataFrame) or df.empty:
            return {"status": "error", "message": f"资讯获取失败: {df}"}

        # 归一化 + 按关联标的过滤
        target = str(ticker).replace(".", "")
        news = []
        for _, row in df.iterrows():
            rel = row.get("related_securities") or []
            rel_codes = [str(r).replace(".", "") for r in (rel if isinstance(rel, list) else [])]
            # 关联标的命中该 ticker 才保留；related_securities 为空时保留（可能是公告/评级）
            if rel_codes and target not in rel_codes:
                continue
            news.append(
                {
                    "headline": str(row.get("title", "")),
                    "category": str(row.get("news_sub_type", "NEWS")),
                    "source": str(row.get("source", "")),
                    "datetime": str(row.get("publish_time", "")),
                    "summary": "",
                    "url": str(row.get("url", "")),
                }
            )
        return {"status": "success", "data": news, "source": "futu", "count": len(news)}

    # ── P1.2: 行情搜索（关键词 → 标的列表，补「名称→代码」盲区）─────────
    @with_global_retry
    async def get_search_quote(self, keyword: str, max_count: int = 10) -> Dict[str, Any]:
        """按关键词搜索标的（补「名称→代码」盲区，Agent 高频刚需）。

        Futu ``get_search_quote(keyword, max_count)`` → (ret, DataFrame)，
        列: market / code / name / sec_type / is_watched。
        支持中文名（如「腾讯」→ HK.00700）与代码（如 AAPL → US.AAPL）。
        高频刚需，带 L1 内存缓存（10 分钟），避免频繁穿透 OpenD。
        """
        keyword = str(keyword or "").strip()
        if not keyword:
            return {"status": "error", "source": "futu", "message": "搜索关键词为空"}
        try:
            max_count = max(1, min(int(max_count), 50))
        except (TypeError, ValueError):
            max_count = 10

        cache_key = f"futu_search_quote_{keyword.lower()}_{max_count}"
        now = time.time()
        cached = self.cache_mgr.get_search_quote_cache(cache_key)
        if cached and now - cached[0] < _SEARCH_QUOTE_TTL:
            return cached[1]

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            ret, df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_search_quote, keyword, max_count)
            if ret != RET_OK or not isinstance(df, pd.DataFrame):
                res = {"status": "error", "source": "futu", "message": f"行情搜索失败: {df}"}
                self.cache_mgr.set_search_quote_cache(cache_key, now, res)
                return res
            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "code": str(row.get("code", "")),
                        "name": str(row.get("name", "")),
                        "market": str(row.get("market", "")),
                        "sec_type": str(row.get("sec_type", "")),
                        "is_watched": bool(row.get("is_watched", False)),
                    }
                )
            res = {"status": "success", "source": "futu", "keyword": keyword, "count": len(results), "data": results}
            self.cache_mgr.set_search_quote_cache(cache_key, now, res)
            return res
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_search_quote 失败 %s: %s", keyword, e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── F4-2: FedWatch FOMC 隐含概率（市场级，无 code 参数）──────────────
    @with_global_retry
    async def get_fed_watch_target_rate(self) -> Dict[str, Any]:
        """获取 FedWatch FOMC 目标利率隐含概率（Tier1 宏观前瞻）。

        支撑 G5。get_fed_watch_target_rate() → (ret, data) 二元组，无 code 参数（全市场）。
        """
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_fed_watch_target_rate)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"FedWatch 获取失败: {data}"}

            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_fed_watch_target_rate 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── P1.8: FedWatch 点阵图（FOMC 委员利率预测散点）──────────────────
    @with_global_retry
    async def get_fed_watch_dot_plot(self) -> Dict[str, Any]:
        """获取 FedWatch 点阵图（FOMC 委员各年利率预测散点）。

        get_fed_watch_dot_plot() → (ret, data) 二元组，无 code 参数（全市场）。
        实测返回 DataFrame 列: year / rate / vote_count / is_median / median_rate / current_rate。
        低频数据，可长 TTL 缓存。
        """
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_fed_watch_dot_plot)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"FedWatch 点阵图获取失败: {data}"}

            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_fed_watch_dot_plot 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── F4-3: 板块热力图（需 market 参数）──────────────────────────────
    @with_global_retry
    async def get_heat_map_data(self, market: str = "HK") -> Dict[str, Any]:
        """获取板块/个股热力图数据（前端 ECharts treemap 数据源）。

        支撑 G6。get_heat_map_data(market) → (ret, data, page) 三元组。
        market 默认 HK（港股），支持 US/SG/A(CN) 等。
        """
        # ⚠️ 市场映射：前端用 'A'/'CN' 表示沪深A股, 实测 futu Market 枚举无 CN,
        #    'A' 映射到 Market.SH(沪市 A 股板块)。不能用 getattr(Market,'A',Market.HK)
        #    — 会 fallback 到港股导致 A 股请求拿到港股数据。
        mkt = _map_heat_market(str(market).upper())
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            from futu import HeatMapPlateType

            # ⚠️ 按 futu 文档显式传 count + plate_type(行业板块), 提高港股/A股板块数据返回成功率。
            #    默认只传 market 时部分 OpenD 配置下可能返回空板块。
            res = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_heat_map_data,
                mkt,
                count=100,
                plate_type=HeatMapPlateType.INDUSTRY,
            )
            if not isinstance(res, (list, tuple)) or len(res) < 2:
                return {"status": "error", "source": "futu", "message": f"热力图返回形态异常: {type(res)}"}
            ret, data = res[0], res[1]
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"热力图获取失败: {data}"}

            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "market": str(mkt).split(".")[-1],
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_heat_map_data 失败 %s: %s", market, e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── F4-5: 港股行业板块资金流聚合（支撑板块资金流向面板）─────────────
    async def get_hk_sector_flow(self) -> Dict[str, Any]:
        """港股行业板块主力净流入聚合（Futu 板块 → 龙头成分股资金流）。

        路径：get_plate_list(HK, INDUSTRY) → get_plate_stock(板块) 取成交额龙头
              → get_capital_distribution(龙头) 聚合主力净流入，作为板块资金流代理。

        限流防护（OpenD 有登录限流铁律）：
          - 只取最多 MAX_PLATES 个行业板块
          - 每板块只取成交额 Top TOP_K 龙头聚合（不拉全量成分股）
          - 整体结果缓存 CACHE_TTL，避免高频穿透
        任一环节失败诚实降级（空 sectors + note），零幻觉。

        返回: {"status", "source", "data": {"market","sectors":[{"name","net_inflow","pct"}],
                                            "unit","updated_at","note"}}
        """
        from futu import Market, Plate

        CACHE_TTL = 1800  # 30 分钟强缓存
        MAX_PLATES = 15  # 最多处理板块数（控制调用量）
        TOP_K = 3  # 每板块龙头数

        cache_key = "futu_hk_sector_flow"
        now = time.time()
        try:
            cached = self.cache_mgr.get_fund_flow_cache(cache_key)
            if cached and now - cached[0] < CACHE_TTL:
                return cached[1]
        except Exception:  # noqa: BLE001
            pass

        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            # 1) 港股行业板块列表
            ret, plate_df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_plate_list, Market.HK, Plate.INDUSTRY)
            if ret != RET_OK or not isinstance(plate_df, pd.DataFrame) or plate_df.empty:
                return {
                    "status": "error",
                    "source": "futu",
                    "message": f"港股行业板块列表获取失败: {plate_df}",
                }

            plate_rows = plate_df.to_dict("records")
            plate_rows = plate_rows[:MAX_PLATES]

            # 2) 逐板块取成分股龙头 → 聚合资金流
            sectors = []
            for pr in plate_rows:
                p_code = str(pr.get("code", ""))
                p_name = str(pr.get("plate_name", "") or pr.get("name", "")).strip()
                if not p_code or not p_name:
                    continue
                try:
                    ret2, stock_df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_plate_stock, p_code)
                    if ret2 != RET_OK or not isinstance(stock_df, pd.DataFrame) or stock_df.empty:
                        continue
                    # 取成交额/市值龙头（优先 turnOver/amount 列，缺省用 code 前 TOP_K）
                    sort_col = next(
                        (c for c in stock_df.columns if str(c).lower() in ("turnover", "amount", "成交额", "mktcap")),
                        None,
                    )
                    top_df = stock_df
                    if sort_col and pd.api.types.is_numeric_dtype(stock_df[sort_col]):
                        top_df = stock_df.sort_values(sort_col, ascending=False)
                    leaders = top_df.head(TOP_K)

                    # 聚合龙头主力净流入（直接调 OpenD get_capital_distribution）
                    net = 0.0
                    valid = 0
                    for _, srow in leaders.iterrows():
                        scode = str(srow.get("code", ""))
                        if not scode:
                            continue
                        try:
                            cret, cdf = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_capital_distribution, scode)
                            if cret != RET_OK or not isinstance(cdf, pd.DataFrame) or cdf.empty:
                                continue
                            crow = cdf.iloc[0]
                            cap_in = safe_float(crow.get("capital_in_super", 0)) + safe_float(
                                crow.get("capital_in_big", 0)
                            )
                            cap_out = safe_float(crow.get("capital_out_super", 0)) + safe_float(
                                crow.get("capital_out_big", 0)
                            )
                            net += cap_in - cap_out
                            valid += 1
                        except Exception:  # noqa: BLE001
                            continue
                    if valid > 0:
                        sectors.append(
                            {
                                "name": p_name,
                                "net_inflow": round(net, 2),
                                "stock_count": valid,
                            }
                        )
                except Exception as e:  # noqa: BLE001
                    logger.warning("[Futu HK板块] %s 聚合失败: %s", p_code, e)
                    continue

            if not sectors:
                res = {
                    "status": "degraded",
                    "source": "futu",
                    "data": {
                        "market": "HK",
                        "market_name": "港股行业板块",
                        "sectors": [],
                        "unit": "港元",
                        "note": "港股行业板块资金流暂不可用（板块数据或资金流接口受限）",
                    },
                }
            else:
                sectors.sort(key=lambda x: x["net_inflow"], reverse=True)
                total_abs = sum(abs(s["net_inflow"]) for s in sectors) or 1
                for s in sectors:
                    s["pct"] = round(abs(s["net_inflow"]) / total_abs, 4)
                res = {
                    "status": "success",
                    "source": "futu",
                    "data": {
                        "market": "HK",
                        "market_name": "港股行业板块",
                        "sectors": sectors,
                        "unit": "港元",
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        "note": "由各板块龙头成分股主力净流入聚合，仅供参考",
                    },
                }
            try:
                self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
            except Exception:  # noqa: BLE001
                pass
            return res
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_hk_sector_flow 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    @with_global_retry
    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 60) -> Dict[str, Any]:  # noqa: E501
        """获取历史K线数据（带缓存和降级策略）"""
        from .utils import format_ticker, is_futu_unsupported

        if is_futu_unsupported(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker(ticker)

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_history(market_ticker, num)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        cache_key = f"futu_history_{market_ticker}_{ktype}"
        now = time.time()
        cached = self.cache_mgr.get_history_cache(cache_key)
        # 💡 日线及以上周期使用更长缓存TTL（1小时），分时线使用短缓存（60秒）
        cache_ttl = 3600.0 if ktype.upper() in ["K_DAY", "K_1D", "K_WEEK", "K_1W", "K_MON", "K_1M"] else 60.0  # noqa: E501
        if cached and now - cached[0] < cache_ttl:
            data = cached[1]
            # 如果缓存的数据量足够，直接切片返回
            if data.get("status") == "success" and "data" in data:
                if len(data["data"]) >= num:
                    return {
                        "status": "success",
                        "ticker": market_ticker,
                        "data": data["data"][-num:],
                    }  # noqa: E501
            else:
                return data

        kt = getattr(KLType, ktype.upper(), KLType.K_DAY)
        st = getattr(SubType, ktype.upper(), SubType.K_DAY)

        # 优化：优先使用 get_cur_kline (消耗订阅额度，比历史额度更宽松)。
        # ⚠️ 注意：get_cur_kline 的 num 上限为 370，超限会报 invalid_parameter 并降级。
        # 日线及以上大跨度需要最大时间数据（前端日线传 num=1000），
        # 若走 get_cur_kline 会触发 num>370 报错再降级, 浪费一次调用, 故直接走 request_history_kline 拉满。
        use_cur_kline = num <= 370

        if use_cur_kline:
            if not self.cache_mgr.has_topic(market_ticker, st):
                # LRU 容量检查
                evicted = self.cache_mgr.ensure_capacity(needed=1)
                await _execute_unsubscriptions(self.conn_mgr, self.cache_mgr, evicted)

                sub_ret, _ = await asyncio.to_thread(
                    self.conn_mgr.quote_ctx.subscribe,
                    [market_ticker],
                    [st],
                    subscribe_push=False,  # noqa: E501
                )
                if sub_ret == RET_OK:
                    self.cache_mgr.touch_topic(market_ticker, st)

            ret, df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_cur_kline, market_ticker, num, kt, AuType.QFQ)
        else:
            ret, df = -1, None

        # 仅在 get_cur_kline 失败(或大跨度 num>370)时, 降级使用 request_history_kline 分页拉取。
        # ⚠️ request_history_kline 单次 max_count 建议 ≤1000 根, 超过会超时/截断;
        #    分页调用: 首页 page_req_key=None, 后续传上次返回的 page_req_key 直到其返回 None,
        #    拼接所有页的数据, 保证日线/周K/月K能拉到 2007 年以来的完整历史。
        if ret != RET_OK or not isinstance(df, pd.DataFrame) or df.empty:
            collected_pages: list[pd.DataFrame] = []
            page_key: str | None = None
            page_count = 0
            max_pages = (num // 800) + 3  # 每页 800 根, 预留缓冲
            while True:
                if page_count >= max_pages:
                    logger.warning("[Futu] history 分页超过 %d 页, 强制停止", max_pages)
                    break
                ret, page_df, page_key = await asyncio.to_thread(
                    self.conn_mgr.quote_ctx.request_history_kline,
                    market_ticker,
                    start=None,
                    end=None,
                    ktype=kt,
                    autype=AuType.QFQ,
                    max_count=min(num, 800),
                    page_req_key=page_key,
                )
                if ret != RET_OK or not isinstance(page_df, pd.DataFrame) or page_df.empty:
                    if ret != RET_OK:
                        res = {"status": "error", "message": f"历史K线获取失败: {page_df}"}
                        self.cache_mgr.set_history_cache(cache_key, now, res)
                        return res
                    break
                collected_pages.append(page_df)
                page_count += 1
                if page_key is None:
                    break
                # 已拉够 num 根则停止（拼接后按时间排序取最旧 num 根）
                fetched_total = sum(len(p) for p in collected_pages)
                if fetched_total >= num:
                    break

            if not collected_pages:
                res = {"status": "error", "message": "历史K线获取失败: 无数据"}
                self.cache_mgr.set_history_cache(cache_key, now, res)
                return res

            # 拼接所有页, 按时间升序; futu 首页返回最新, 翻页返回更早, 拼接后即完整序列。
            # 取最近的 num 根 (K线图默认展示最近数据; 周线 num=1000 可覆盖约 19 年, 即到 2007 年)。
            if len(collected_pages) > 1:
                df = pd.concat(collected_pages, ignore_index=True)
            else:
                df = collected_pages[0]
            df = df.sort_values("time_key", ascending=True).reset_index(drop=True)
            if len(df) > num:
                df = df.iloc[-num:]  # 保留最近 num 根

        kl_list = []
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                kl_list.append(
                    {
                        "time": str(row.get("time_key", "")),
                        "open": float(row.get("open", 0.0)),
                        "high": float(row.get("high", 0.0)),
                        "low": float(row.get("low", 0.0)),
                        "close": float(row.get("close", 0.0)),
                        "volume": float(row.get("volume", 0.0)),
                    }
                )

        res = {"status": "success", "ticker": market_ticker, "data": kl_list}
        self.cache_mgr.set_history_cache(cache_key, now, res)
        return res

    @with_global_retry
    async def subscribe_quote(self, ticker: str, format_ticker_func, is_unsupported_func) -> Dict[str, Any]:  # noqa: E501
        """BE-ARCH-08c⑤: 向 OpenD 订阅个股实时推送 (QUOTE + ORDER_BOOK, subscribe_push=True)。

        此前订阅仅作为 get_quote 的副作用发生, 前端 WS 新订阅标的无法通知 OpenD 去订阅,
        只能等主服务 broadcast_loop 约 10s 轮询"碰巧"触发 → 实时推送对新标的长期滞后。
        本方法供 futu_worker 的 SUBSCRIBE action 直接调用, 实现前端订阅 → 子服务 → OpenD
        的实时订阅回传闭环。逻辑与 get_quote 内联订阅段保持一致 (LRU 容量 + 双类型订阅)。
        """
        if is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker)

        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            # 开发环境 Mock 视为订阅成功 (无真实 OpenD)
            self.cache_mgr.touch_topic(market_ticker, SubType.QUOTE)
            self.cache_mgr.touch_topic(market_ticker, SubType.ORDER_BOOK)
            return {"status": "success", "subscribed": [market_ticker], "mode": "mock"}

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        if self.cache_mgr.has_topic(market_ticker, SubType.QUOTE):
            return {"status": "success", "subscribed": [market_ticker], "already": True}

        # LRU 容量检查：超限时淘汰最久未用的订阅
        evicted = self.cache_mgr.ensure_capacity(needed=2)  # 💡 需要2个槽位：QUOTE + ORDER_BOOK
        await _execute_unsubscriptions(self.conn_mgr, self.cache_mgr, evicted)

        ret, msg = self.conn_mgr.quote_ctx.subscribe(
            [market_ticker],
            [SubType.QUOTE, SubType.ORDER_BOOK],
            subscribe_push=True,  # 开启推送，实时报价 + 盘口深度通过 PushHandler 桥接到 Redis
            extended_time=True,  # noqa: E501
        )
        if ret != RET_OK:
            return {"status": "error", "message": msg}
        self.cache_mgr.touch_topic(market_ticker, SubType.QUOTE)
        self.cache_mgr.touch_topic(market_ticker, SubType.ORDER_BOOK)
        return {"status": "success", "subscribed": [market_ticker]}

    @with_global_retry
    async def unsubscribe_quote(self, ticker: str, format_ticker_func) -> Dict[str, Any]:  # noqa: E501
        """退订个股行情，释放 OpenD 订阅额度槽位"""
        market_ticker = format_ticker_func(ticker)

        if not self.conn_mgr.quote_ctx or self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "message": "Futu OpenD 未连接"}

        try:

            def _do_unsub():
                # 退订高频占用槽位的行情推送类型 (包含基础报价、深度摆盘、逐笔成交、席位等)  # noqa: E501
                sub_types = [
                    SubType.QUOTE,
                    SubType.ORDER_BOOK,
                    SubType.TICKER,
                    SubType.BROKER,
                    SubType.K_DAY,
                ]  # noqa: E501
                ret, data = self.conn_mgr.quote_ctx.unsubscribe([market_ticker], sub_types)  # noqa: E501

                if ret == RET_OK:
                    # 同步清理内部的主题追踪缓存
                    for st in sub_types:
                        self.cache_mgr.remove_topic(market_ticker, st)
                    return {"status": "success", "message": f"成功退订 {market_ticker}"}
                return {"status": "error", "message": str(data)}

            return await asyncio.to_thread(_do_unsub)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @with_global_retry
    async def get_order_book(self, ticker: str, format_ticker_func, is_unsupported_func) -> Dict[str, Any]:  # noqa: E501
        """获取实时 Level 2 盘口深度数据"""
        if is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker)

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_order_book(market_ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # L1 极速内存缓存 (TTL: 1秒)
        cache_key = f"futu_ob_{market_ticker}"
        now = time.time()
        cached = self.cache_mgr.get_order_book_cache(cache_key)
        if cached and now - cached[0] < 1.0:
            return cached[1]

        if not self.cache_mgr.has_topic(market_ticker, SubType.ORDER_BOOK):
            # LRU 容量检查
            evicted = self.cache_mgr.ensure_capacity(needed=1)
            await _execute_unsubscriptions(self.conn_mgr, self.cache_mgr, evicted)

            ret, msg = self.conn_mgr.quote_ctx.subscribe(
                [market_ticker], [SubType.ORDER_BOOK], subscribe_push=True
            )  # 开启推送，盘口深度实时推送
            if ret != RET_OK:
                return {"status": "error", "message": f"盘口订阅失败: {msg}"}
            self.cache_mgr.touch_topic(market_ticker, SubType.ORDER_BOOK)

        ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_order_book, market_ticker)
        if ret != RET_OK or not isinstance(data, dict):
            return {"status": "error", "message": f"盘口获取失败: {data}"}

        bids = [{"price": float(p), "size": int(v)} for p, v, *_ in data.get("Bid", [])]
        asks = [{"price": float(p), "size": int(v)} for p, v, *_ in data.get("Ask", [])]
        result = {
            "status": "success",
            "ticker": market_ticker,
            "bids": bids,
            "asks": asks,
        }  # noqa: E501
        self.cache_mgr.set_order_book_cache(cache_key, now, result)
        return result
