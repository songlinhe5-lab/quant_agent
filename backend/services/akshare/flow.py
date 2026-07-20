"""沪深港通资金流向 Mixin (南向/北向/个股持仓)"""

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry


class FlowMixin:
    """沪深港通资金流向数据获取"""

    @with_global_retry
    async def get_southbound_flow(self) -> Dict[str, Any]:
        """
        获取港股通南向资金当日累计净买入金额（亿元人民币）。
        数据来源: 东方财富沪深港通实时数据

        返回格式:
        {
            "status": "success",
            "data": {
                "net_inflow": 12.8,       # 当日南向净买入 (亿人民币)
                "balance": 105.0,         # 当日余额
                "quota": 105.0,           # 每日额度
                "date": "2026-06-03",
                "sparkline": [...],       # 近8日净流入序列
            }
        }
        """
        cache_key = "akshare_southbound_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        # DIST-07 方案A: cache 模式下不直连 akshare，数据由北京 VPS 中继写入 Redis
        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 南向资金缓存未命中，等待北京 VPS 采集器写入",
                "data": None,
            }

        try:
            import akshare as ak

            # stock_hsgt_fund_flow_summary_em: 沪深港通资金流向汇总
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁：防止排队的并发请求将缓存击穿
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                # 💡 并发拉取 实时汇总 和 历史趋势
                df, hist_df = await asyncio.gather(
                    asyncio.to_thread(ak.stock_hsgt_fund_flow_summary_em),
                    asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="南向资金"),
                    return_exceptions=True,
                )

            if isinstance(df, BaseException) or df is None or df.empty:
                raise ValueError(f"获取到的资金流向汇总数据异常: {df}")

            # 筛选南向资金 (包含港股通沪与港股通深)
            south_df = df[df["资金方向"] == "南向"]
            if south_df.empty:
                raise ValueError("未在数据中找到南向资金方向的明细")

            net_inflow = float(south_df["资金净流入"].sum())

            date_str = str(south_df["交易日"].iloc[0])

            # 💡 提取真实的近期历史趋势线
            sparkline = [1, 1, -1, 1, 1, 1, -1, 1]
            if not isinstance(hist_df, BaseException) and hist_df is not None and not hist_df.empty:  # noqa: E501
                # 💡 修复：优先使用 "当日成交净买额" (真实净买卖) 而非 "当日资金流入" (额度占用)  # noqa: E501
                target_col = "当日成交净买额" if "当日成交净买额" in hist_df.columns else "当日资金流入"  # noqa: E501
                if target_col in hist_df.columns:
                    sparkline = hist_df[target_col].tail(8).astype(float).tolist()
                    # 💡 智能拯救：如果实时接口返回了额度占位符(>800亿)，利用历史趋势的最后一天真实数据进行替换拯救！  # noqa: E501
                    if net_inflow >= 800.0 and len(sparkline) > 0:
                        net_inflow = float(sparkline[-1])

            if net_inflow >= 800.0:
                raise ValueError("AKShare 返回了总额度而非净流入，且无法用历史数据拯救，判定为接口异常")  # noqa: E501

            # 状态判定：3 为已收盘
            is_closed = int(south_df["交易状态"].iloc[0]) == 3 if "交易状态" in south_df.columns else False  # noqa: E501

            result = {
                "status": "success",
                "data": {
                    "net_inflow": round(net_inflow, 2),
                    "unit": "亿人民币",
                    "date": date_str,
                    "sparkline": sparkline,
                },
                "is_closed": is_closed,
                "source": "akshare_stock_hsgt_fund_flow_summary",
            }
        except Exception as e:
            print(f"⚠️ [AKShare] 南向资金获取失败: {e}")
            result = self._mock_southbound()

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 成功时智能缓存：盘中缓存 5 分钟，已收盘则长效缓存 12 小时
        if result.get("status") == "success":
            # 💡 增加随机 Jitter 防雪崩
            ttl = (43200 if result.get("is_closed") else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_northbound_flow(self) -> Dict[str, Any]:
        """
        获取北向资金（外资买入A股）当日累计净买入金额。

        返回格式:
        {
            "status": "success",
            "data": {
                "net_inflow": -5.3,
                "unit": "亿人民币",
                "date": "2026-06-03",
                "sparkline": [...],
            }
        }
        """
        cache_key = "akshare_northbound_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 北向资金缓存未命中，等待北京 VPS 采集器写入",
                "data": None,
            }

        try:
            import akshare as ak

            # stock_hsgt_fund_flow_summary_em: 沪深港通资金流向汇总
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁：防止排队的并发请求将缓存击穿
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                # 💡 并发拉取 实时汇总 和 历史趋势
                df, hist_df = await asyncio.gather(
                    asyncio.to_thread(ak.stock_hsgt_fund_flow_summary_em),
                    asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="北向资金"),
                    return_exceptions=True,
                )

            if isinstance(df, BaseException) or df is None or df.empty:
                raise ValueError(f"获取到的资金流向汇总数据异常: {df}")

            # 筛选北向资金 (包含沪股通与深股通)
            north_df = df[df["资金方向"] == "北向"]
            if north_df.empty:
                raise ValueError("未在数据中找到北向资金方向的明细")

            net_inflow = float(north_df["资金净流入"].sum())

            date_str = str(north_df["交易日"].iloc[0])

            # 💡 提取真实的近期历史趋势线
            sparkline = [-1, -1, 1, -1, -1, 1, -1, -1]
            if not isinstance(hist_df, BaseException) and hist_df is not None and not hist_df.empty:  # noqa: E501
                # 💡 修复：优先使用 "当日成交净买额" (真实净买卖) 而非 "当日资金流入" (额度占用)  # noqa: E501
                target_col = "当日成交净买额" if "当日成交净买额" in hist_df.columns else "当日资金流入"  # noqa: E501
                if target_col in hist_df.columns:
                    sparkline = hist_df[target_col].tail(8).astype(float).tolist()
                    # 💡 智能拯救北向：如果实时接口返回额度占位符(>1000亿)
                    if net_inflow >= 1000.0 and len(sparkline) > 0:
                        net_inflow = float(sparkline[-1])

            # 状态判定：3 为已收盘
            is_closed = int(north_df["交易状态"].iloc[0]) == 3 if "交易状态" in north_df.columns else False  # noqa: E501

            # 💡 健壮性修复：如果返回的值大于等于每日总额度(1000亿以上)，说明接口异常
            if net_inflow >= 1000.0:
                raise ValueError("AKShare 返回了总额度而非净流入，且无法用历史数据拯救，判定为接口异常")  # noqa: E501

            result = {
                "status": "success",
                "data": {
                    "net_inflow": round(net_inflow, 2),
                    "unit": "亿人民币",
                    "date": date_str,
                    "sparkline": sparkline,
                },
                "is_closed": is_closed,
                "source": "akshare_stock_hsgt_fund_flow_summary",
            }
        except Exception as e:
            print(f"⚠️ [AKShare] 北向资金获取失败: {e}")
            result = self._mock_northbound()

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 成功时智能缓存：盘中缓存 5 分钟，已收盘则长效缓存 12 小时
        if result.get("status") == "success":
            # 💡 增加随机 Jitter 防雪崩
            ttl = (43200 if result.get("is_closed") else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_hsgt_top_holders(self, symbol: str = "00700") -> Dict[str, Any]:
        """
        获取沪深港通个股持仓明细（按参与机构汇总），用于推算外资/南下托管行持股变化。
        (已升级为使用 stock_hsgt_individual_detail_em 获取更精准的互联互通机构明细)

        参数:
            symbol: 纯数字代码，如 "00700" (港股) 或 "002008" (A股)

        返回:
            {
                "status": "success",
                "data": {
                    "symbol": "00700",
                    "total_shares": ...,
                    "participants": [...],
                    "southbound_proxy": ...  # 南下资金托管行合计
                }
            }
        """
        cache_key = f"akshare_hsgt_holders_{symbol}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": f"cache 模式: {symbol} 持股明细缓存未命中",
                "data": None,
            }

        try:
            import akshare as ak

            # 动态推断最近 20 天以确保命中交易日
            today = datetime.now()
            end_date = today.strftime("%Y%m%d")
            start_date = (today - timedelta(days=20)).strftime("%Y%m%d")

            # stock_hsgt_individual_detail_em: 沪深港通具体股票机构持股详情 (替代废弃的 CCASS 接口)  # noqa: E501
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                df = await asyncio.to_thread(
                    ak.stock_hsgt_individual_detail_em,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
            if df is None or df.empty:
                raise ValueError(f"沪深港通持股明细数据为空 ({symbol})")

            # 获取最近两个交易日的日期
            dates = sorted(df["持股日期"].unique(), reverse=True)
            latest_date = dates[0]
            prev_date = dates[1] if len(dates) > 1 else None

            # 筛选最新与上一交易日的数据
            latest_df = df[df["持股日期"] == latest_date]
            prev_df = df[df["持股日期"] == prev_date] if prev_date else None

            # 构建上一交易日机构持仓映射表，用于对比计算
            prev_map = (
                {str(row.get("机构名称", "")): float(row.get("持股数量", 0) or 0) for _, row in prev_df.iterrows()}
                if prev_df is not None and not prev_df.empty
                else {}
            )  # noqa: E501

            # 按照持股数量降序排列以获取 Top 机构
            if "持股数量" in latest_df.columns:
                latest_df = latest_df.sort_values(by="持股数量", ascending=False)

            # 极其精准的南向/北向总股数 (直接进行全表加和)
            southbound_total = float(latest_df["持股数量"].sum())
            prev_southbound_total = (
                float(prev_df["持股数量"].sum()) if prev_df is not None and not prev_df.empty else southbound_total
            )  # noqa: E501
            total_net_change = southbound_total - prev_southbound_total
            total_holdings = southbound_total

            participants_summary = []
            for _, row in latest_df.head(20).iterrows():
                holder = str(row.get("机构名称", ""))
                shares = float(row.get("持股数量", 0) or 0)
                pct = float(row.get("持股数量占A股百分比", row.get("占已发行股份百分比", 0)) or 0)  # noqa: E501

                # 计算该机构的净增持
                prev_shares = prev_map.get(holder, shares)
                net_change = shares - prev_shares

                participants_summary.append(
                    {
                        "holder": holder,
                        "shares": round(shares, 0),
                        "net_change": round(net_change, 0),
                        "pct": round(pct, 2),
                        "is_southbound": True,  # 来源于沪深港通接口，全部为互联互通资金
                    }
                )

            result = {
                "status": "success",
                "data": {
                    "symbol": symbol,
                    "date": str(latest_date),
                    "southbound_total_shares": round(southbound_total, 0),
                    "southbound_net_change": round(total_net_change, 0),
                    "participants": participants_summary,
                    "total_shares_sampled": round(total_holdings, 0),
                },
                "source": "akshare_stock_hsgt_individual_detail",
            }
        except Exception as e:
            print(f"⚠️ [AKShare] CCASS {symbol} 获取失败: {e}")
            result = {
                "status": "warning" if isinstance(e, ValueError) else "error",
                "message": str(e),
                "data": None,
            }

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 仅当获取成功时进行 12 小时长效缓存 (互联互通明细为 T-1 盘后数据，每天更新一次即可)  # noqa: E501
        if result.get("status") == "success":
            ttl = 43200 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)  # 错误状态仅做短时防穿透  # noqa: E501
        return result
