"""技术指标计算 Mixin"""

import asyncio
from typing import Any, Dict, List, Optional, cast

import pandas as pd


class TechnicalMixin:
    """技术指标计算引擎 (MA/RSI/MACD/KDJ/ATR/BOLL)"""

    async def get_tech_indicators(
        self,
        ticker: str,
        ma_periods: Optional[List[int]] = None,
        rsi_period: int = 14,
        include_macd: bool = True,
        include_kdj: bool = True,
        atr_period: int = 14,
        stop_loss_multiplier: float = 2.0,
        take_profit_multiplier: float = 3.0,
        lookback_days: int = 1,
        bbands_period: int = 20,
        bbands_std_dev: float = 2.0,
        pre_fetched_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:  # noqa: E501
        if ma_periods is None:
            ma_periods = [10, 20]  # noqa: E701
        lookback_days = max(1, min(lookback_days, 30))

        df = pre_fetched_df
        if df is None:
            success, df, msg = await self.fetch_yf_data(
                ticker, "history", ttl=3600, persist=False, period="6mo", progress=False
            )  # noqa: E501
            if not success:
                # 将降级条件放宽，一旦获取失败就使用 mock 数据进行界面展示
                if (
                    msg == "development_mock"
                    or "数据无效" in msg
                    or "限流冷却" in msg
                    or "无效标的" in msg
                    or "返回空数据" in msg
                    or "网络" in msg
                    or "timeout" in msg.lower()
                ):
                    fallback_data = self._mock_tech_data(
                        ticker,
                        ma_periods,
                        rsi_period,
                        include_macd,
                        atr_period,
                        stop_loss_multiplier,
                        take_profit_multiplier,
                        lookback_days,
                        bbands_period,
                        bbands_std_dev,
                    )  # noqa: E501
                    fallback_data["message"] = f"⚠️ {msg} (已自动降级为本地缓存/模拟数据)"  # noqa: E501
                    return fallback_data
                return {"status": "error", "message": msg}

        if df is None or df.empty:
            return {"status": "error", "message": "返回的数据为空，无法计算技术指标。"}

        try:
            # 💡 性能修复：将计算技术指标中极度耗时的 Pandas Rolling/Ewm 等强运算全部封装入线程池  # noqa: E501
            def _compute_tech(local_df: pd.DataFrame):
                if local_df is None or not hasattr(local_df, "empty") or local_df.empty:
                    raise ValueError("计算指标失败：输入数据为空或非法类型")
                open_series = cast(
                    pd.Series,
                    local_df["Open"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Open"],
                )  # noqa: E501
                close_series = cast(
                    pd.Series,
                    local_df["Close"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Close"],
                )  # noqa: E501
                high_series = cast(
                    pd.Series,
                    local_df["High"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["High"],
                )  # noqa: E501
                low_series = cast(
                    pd.Series,
                    local_df["Low"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Low"],
                )  # noqa: E501
                volume_series = cast(
                    pd.Series,
                    local_df["Volume"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Volume"],
                )  # noqa: E501

                ma_dict = {p: close_series.rolling(window=p).mean() for p in ma_periods}
                rsi_series = None
                if rsi_period and rsi_period > 0:
                    delta = close_series.diff()
                    gain, loss = (
                        delta.where(delta > 0, 0.0),
                        -delta.where(delta < 0, 0.0),
                    )  # noqa: E501
                    rs = (
                        gain.ewm(alpha=1 / rsi_period, adjust=False).mean()
                        / loss.ewm(alpha=1 / rsi_period, adjust=False).mean()
                    )  # noqa: E501
                    rsi_series = 100 - (100 / (1 + rs))

                macd_hist, macd_line, signal_line = None, None, None
                if include_macd:
                    macd_line = (
                        close_series.ewm(span=12, adjust=False).mean() - close_series.ewm(span=26, adjust=False).mean()
                    )  # noqa: E501
                    signal_line = macd_line.ewm(span=9, adjust=False).mean()
                    macd_hist = macd_line - signal_line

                k_series, d_series, j_series = None, None, None
                if include_kdj:
                    # KDJ 标准算法 (N=9, M1=3, M2=3)
                    high_9 = high_series.rolling(window=9, min_periods=1).max()
                    low_9 = low_series.rolling(window=9, min_periods=1).min()
                    rsv = (close_series - low_9) / (high_9 - low_9) * 100
                    k_series = rsv.fillna(50).ewm(com=2, adjust=False).mean()  # com=2 等价于 alpha=1/3  # noqa: E501
                    d_series = k_series.ewm(com=2, adjust=False).mean()
                    j_series = 3 * k_series - 2 * d_series

                atr_series = None
                if atr_period and atr_period > 0:
                    tr = pd.concat(
                        [
                            high_series - low_series,
                            (high_series - close_series.shift(1)).abs(),
                            (low_series - close_series.shift(1)).abs(),
                        ],
                        axis=1,
                    ).max(axis=1)  # noqa: E501
                    atr_series = tr.ewm(alpha=1 / atr_period, adjust=False).mean()

                bb_middle, bb_upper, bb_lower = None, None, None
                if bbands_period and bbands_period > 0:
                    bb_middle = close_series.rolling(window=bbands_period).mean()
                    bb_std = close_series.rolling(window=bbands_period).std()
                    bb_upper, bb_lower = (
                        bb_middle + bbands_std_dev * bb_std,
                        bb_middle - bbands_std_dev * bb_std,
                    )  # noqa: E501

                trend_data = []
                for i in range(-lookback_days, 0):
                    if i < -len(close_series):
                        continue  # noqa: E701
                    day_res = {
                        "date": str(close_series.index[i].date()),
                        "open": round(float(open_series.iloc[i]), 2),
                        "high": round(float(high_series.iloc[i]), 2),
                        "low": round(float(low_series.iloc[i]), 2),
                        "close": round(float(close_series.iloc[i]), 2),
                        "volume": int(volume_series.iloc[i]),
                    }  # noqa: E501
                    for p in ma_periods:
                        day_res[f"MA_{p}"] = round(float(ma_dict[p].iloc[i]), 2)  # noqa: E501, E701
                    if rsi_series is not None:
                        day_res[f"RSI_{rsi_period}"] = round(float(rsi_series.iloc[i]), 2)  # noqa: E501, E701
                    if (
                        include_macd
                        and (macd_line is not None)
                        and (signal_line is not None)
                        and (macd_hist is not None)
                    ):
                        day_res.update(
                            {
                                "MACD_line": round(float(macd_line.iloc[i]), 3),
                                "MACD_signal": round(float(signal_line.iloc[i]), 3),
                                "MACD_hist": round(float(macd_hist.iloc[i]), 3),
                            }
                        )  # noqa: E501, E701
                    if include_kdj and (k_series is not None) and (d_series is not None) and (j_series is not None):
                        day_res.update(
                            {
                                "KDJ_K": round(float(k_series.iloc[i]), 2),
                                "KDJ_D": round(float(d_series.iloc[i]), 2),
                                "KDJ_J": round(float(j_series.iloc[i]), 2),
                            }
                        )  # noqa: E501, E701
                    if atr_series is not None:
                        curr_atr = float(atr_series.iloc[i])
                        day_res[f"ATR_{atr_period}"] = round(curr_atr, 3)
                        if ma_periods and day_res.get(f"MA_{ma_periods[0]}"):
                            day_res.update(
                                {
                                    "trailing_stop_loss": round(
                                        day_res[f"MA_{ma_periods[0]}"] - stop_loss_multiplier * curr_atr,
                                        2,
                                    ),
                                    "take_profit": round(
                                        day_res[f"MA_{ma_periods[0]}"] + take_profit_multiplier * curr_atr,
                                        2,
                                    ),
                                }
                            )  # noqa: E501, E701
                    if (bb_middle is not None) and (bb_upper is not None) and (bb_lower is not None):
                        day_res.update(
                            {
                                f"BB_middle_{bbands_period}": round(float(bb_middle.iloc[i]), 2),
                                f"BB_upper_{bbands_period}": round(float(bb_upper.iloc[i]), 2),
                                f"BB_lower_{bbands_period}": round(float(bb_lower.iloc[i]), 2),
                            }
                        )  # noqa: E501, E701

                    actions = []
                    if i - 1 >= -len(close_series):
                        if include_macd and macd_hist is not None:
                            actions.append("buy (MACD金叉)") if macd_hist.iloc[i] > 0 and macd_hist.iloc[
                                i - 1
                            ] <= 0 else actions.append("sell (MACD死叉)") if macd_hist.iloc[i] < 0 and macd_hist.iloc[
                                i - 1
                            ] >= 0 else None  # noqa: E501, E701
                        if include_kdj and (k_series is not None) and (d_series is not None):
                            actions.append("buy (KDJ金叉)") if k_series.iloc[i] > d_series.iloc[i] and k_series.iloc[
                                i - 1
                            ] <= d_series.iloc[i - 1] else actions.append("sell (KDJ死叉)") if k_series.iloc[
                                i
                            ] < d_series.iloc[i] and k_series.iloc[i - 1] >= d_series.iloc[i - 1] else None  # noqa: E501, E701
                        if ma_periods and len(ma_periods) >= 2:
                            actions.append(f"buy (MA{ma_periods[0]}上穿MA{ma_periods[1]})") if ma_dict[
                                ma_periods[0]
                            ].iloc[i] > ma_dict[ma_periods[1]].iloc[i] and ma_dict[ma_periods[0]].iloc[
                                i - 1
                            ] <= ma_dict[ma_periods[1]].iloc[i - 1] else actions.append(
                                f"sell (MA{ma_periods[0]}下穿MA{ma_periods[1]})"
                            ) if ma_dict[ma_periods[0]].iloc[i] < ma_dict[ma_periods[1]].iloc[i] and ma_dict[
                                ma_periods[0]
                            ].iloc[i - 1] >= ma_dict[ma_periods[1]].iloc[i - 1] else None  # noqa: E501, E701
                        if (bb_upper is not None) and (bb_lower is not None):
                            actions.append("buy (突破布林带上轨)") if close_series.iloc[i] > bb_upper.iloc[
                                i
                            ] and close_series.iloc[i - 1] <= bb_upper.iloc[i - 1] else actions.append(
                                "sell (跌破布林带下轨)"
                            ) if close_series.iloc[i] < bb_lower.iloc[i] and close_series.iloc[i - 1] >= bb_lower.iloc[
                                i - 1
                            ] else None  # noqa: E501, E701

                        # 💡 RSI 顶底背离探测逻辑 (简易高频版：过去 5 日对比，加入成交量辅助判断)  # noqa: E501
                        if rsi_series is not None and i - 5 >= -len(close_series):
                            vol_avg = volume_series.iloc[i - 5 : i].mean()
                            curr_vol = volume_series.iloc[i]

                            is_shrink = curr_vol < vol_avg * 0.8
                            is_expand = curr_vol > vol_avg * 1.2

                            # 底背离 (价格创新低，但 RSI 处在超卖区反弹)
                            if (
                                close_series.iloc[i] < close_series.iloc[i - 1]
                                and close_series.iloc[i] <= close_series.iloc[i - 5 : i].min()
                                and rsi_series.iloc[i] > rsi_series.iloc[i - 1]
                                and rsi_series.iloc[i] < 40
                            ):  # noqa: E501
                                if is_shrink:
                                    actions.append("buy (RSI底背离+缩量企稳)")
                                elif is_expand:
                                    actions.append("buy (RSI底背离+放量抢筹)")
                                else:
                                    actions.append("buy (疑似RSI底背离)")

                            # 顶背离 (价格创新高，但 RSI 处在超买区回落)
                            elif (
                                close_series.iloc[i] > close_series.iloc[i - 1]
                                and close_series.iloc[i] >= close_series.iloc[i - 5 : i].max()
                                and rsi_series.iloc[i] < rsi_series.iloc[i - 1]
                                and rsi_series.iloc[i] > 60
                            ):  # noqa: E501
                                if is_shrink:
                                    actions.append("sell (RSI顶背离+缩量滞涨)")
                                elif is_expand:
                                    actions.append("sell (RSI顶背离+放量出货)")
                                else:
                                    actions.append("sell (疑似RSI顶背离)")

                    day_res["action"] = " | ".join(actions) if actions else "hold"

                    # 💡 动态多空趋势综合评分 (0-100)
                    trend_score = 50.0
                    if ma_periods and len(ma_periods) >= 1:
                        ma_short = float(ma_dict[ma_periods[0]].iloc[i])
                        trend_score += 15 if close_series.iloc[i] > ma_short else -15

                        if len(ma_periods) >= 2:
                            ma_long = float(ma_dict[ma_periods[1]].iloc[i])
                            trend_score += 15 if ma_short > ma_long else -15

                        if atr_series is not None:
                            curr_atr = float(atr_series.iloc[i])
                            if curr_atr > 0:
                                # 计算价格偏离短均线的 ATR 倍数 (偏离 2 倍 ATR 即拉满 20 分)  # noqa: E501
                                atr_dist = (close_series.iloc[i] - ma_short) / curr_atr
                                trend_score += max(-20.0, min(20.0, atr_dist * 10))

                    # 💡 量价配合加分 (±10分)：放量上涨加分，放量下跌扣分
                    if i - 5 >= -len(close_series):
                        vol_avg = volume_series.iloc[i - 5 : i].mean()
                        curr_vol = volume_series.iloc[i]
                        # 当日成交量较过去 5 日均量放大 20% 即视为有效放量
                        if vol_avg > 0 and curr_vol > vol_avg * 1.2:
                            is_up = close_series.iloc[i] >= open_series.iloc[i]
                            trend_score += 10 if is_up else -10

                    day_res["trend_score"] = int(max(0, min(100, trend_score)))
                    trend_data.append(day_res)
                return {
                    "status": "success",
                    "data": {
                        "ticker": ticker,
                        "lookback_days": len(trend_data),
                        "trend": trend_data,
                    },
                }  # noqa: E501

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, _compute_tech, df)
        except Exception as e:
            return {"status": "error", "message": f"技术指标计算发生异常: {str(e)}"}

    def _mock_tech_data(
        self,
        ticker: str,
        ma_periods: List[int],
        rsi_period: int,
        include_macd: bool,
        atr_period: int,
        stop_loss_multiplier: float,
        take_profit_multiplier: float,
        lookback_days: int,
        bbands_period: int,
        bbands_std_dev: float,
    ) -> Dict[str, Any]:  # noqa: E501
        trend = []
        for i in range(lookback_days):
            day_data = {
                "date": f"2026-05-{20 + i}",
                "open": 144.5 + i,
                "high": 146.5 + i,
                "low": 143.5 + i,
                "close": 145.5 + i,
                "volume": 1200000 + i * 50000,
                "MA_10": 145.5,
                "MA_20": 142.1,
                "RSI_14": 65.4,
                "trend_score": 85,
                "action": "buy (MACD金叉)" if i == lookback_days - 1 else "hold",
            }  # noqa: E501
            if include_macd:
                day_data.update({"MACD_line": 1.25, "MACD_signal": 0.85, "MACD_hist": 0.40})  # noqa: E501, E701
            if atr_period:
                day_data.update(
                    {
                        f"ATR_{atr_period}": 5.94,
                        "trailing_stop_loss": round(145.5 - (stop_loss_multiplier * 5.94), 2),
                        "take_profit": round(145.5 + (take_profit_multiplier * 5.94), 2),
                    }
                )  # noqa: E501, E701
            if bbands_period:
                day_data.update(
                    {
                        f"BB_middle_{bbands_period}": 142.1,
                        f"BB_upper_{bbands_period}": 148.5,
                        f"BB_lower_{bbands_period}": 135.7,
                    }
                )  # noqa: E501, E701
            trend.append(day_data)
        return {
            "status": "success",
            "message": "未安装依赖，返回 Mock 数据",
            "data": {"ticker": ticker, "lookback_days": lookback_days, "trend": trend},
        }  # noqa: E501
