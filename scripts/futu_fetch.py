#!/usr/bin/env python3
"""
量化数据源连通性验证脚本
遍历 12 个宏观/市场标的，优先从 Futu OpenD 获取实时快照，
失败时自动降级至 Yahoo Finance (yfinance)。
"""

import time
import sys
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from futu import (
    OpenQuoteContext, SubType, RET_OK, KLType, AuType,
)

# ─── 12 大宏观标的定义 ───────────────────────────────────────────────
# 注意：富途不支持债券、外汇、商品期货，这些天然会走 yfinance 降级
# futu_code 设为 None 表示直接跳过富途尝试

TARGETS = [
    # (名称, futu_code, yf_ticker, 类型)
    ("S&P 500",           "US.SPX",   "^GSPC",       "指数"),
    ("NASDAQ 综合",        "US.IXIC",  "^IXIC",       "指数"),
    ("恒生指数",            "HK.800000","^HSI",        "指数"),
    ("10Y 美债收益率",       None,       "^TNX",        "债券"),
    ("USD/JPY",            None,       "JPY=X",       "外汇"),
    ("美元指数 (DXY)",       None,       "DX-Y.NYB",   "外汇"),
    ("USD/CNH",            None,       "CNH=X",       "外汇"),
    ("比特币 (BTC)",         None,       "BTC-USD",     "加密货币"),
    ("黄金 (XAU)",          None,       "GC=F",        "商品"),
    ("WTI 原油",            None,       "CL=F",        "商品"),
    ("VIX 恐慌指数",         "US.VIX",   "^VIX",        "指数"),
    ("日经 225",            None,       "^N225",       "指数"),
]


@dataclass
class Result:
    name: str
    ticker: str
    price: Optional[float]
    change_pct: Optional[float]
    volume: Optional[str]
    source: str   # "futu" | "yfinance" | "failed"
    error: str

    def ok(self) -> bool:
        return self.price is not None


def try_futu(quote_ctx: OpenQuoteContext, futu_code: str) -> Result | None:
    """尝试从富途获取快照，返回 Result 或 None（表示不支持/断开）"""
    if not quote_ctx:
        return None
    try:
        # 订阅 + 获取快照
        ret_sub, _ = quote_ctx.subscribe([futu_code], [SubType.QUOTE], subscribe_push=False)
        if ret_sub != RET_OK:
            return None  # 订阅失败，不抛异常，交给 yfinance

        ret, df = quote_ctx.get_market_snapshot([futu_code])
        if ret != RET_OK or not isinstance(df, pd.DataFrame) or df.empty:
            return None

        row = df.iloc[0]
        last = float(row.get("last_price", 0)) or float(row.get("cur_price", 0))
        prev = float(row.get("prev_close_price", 0))
        chg = ((last - prev) / prev * 100) if prev and prev > 0 else None
        vol = float(row.get("volume", 0))

        vol_str = (
            f"{vol / 1e9:.2f}B" if vol >= 1e9
            else f"{vol / 1e6:.2f}M" if vol >= 1e6
            else f"{vol / 1e3:.2f}K" if vol >= 1e3
            else str(int(vol))
        )

        return Result(
            name="",
            ticker=futu_code,
            price=last,
            change_pct=chg,
            volume=vol_str,
            source="futu (富途)",
            error="",
        )
    except Exception as e:
        return None


def try_yfinance(name: str, yf_ticker: str | None) -> Result:
    """尝试从 Yahoo Finance 获取最新价格"""
    try:
        import yfinance as yf
        import requests
        
        class TimeoutSession(requests.Session):
            def request(self, method, url, **kwargs):
                kwargs.setdefault('timeout', 10.0)
                return super().request(method, url, **kwargs)

        if yf_ticker is None:
            return Result(
                name=name,
                ticker="N/A",
                price=None,
                change_pct=None,
                volume=None,
                source="failed",
                error="yfinance 不支持该标的（无可用代码）",
            )

        ticker = yf.Ticker(yf_ticker, session=TimeoutSession())
        # fast_info 比 .info 更快更稳定
        fast = ticker.fast_info
        last = fast.get("lastPrice") or fast.get("regularMarketPrice") or fast.get("previousClose")

        if last is None:
            # 降级到 info
            info = ticker.info
            last = info.get("regularMarketPrice") or info.get("previousClose") or info.get("currentPrice")
            prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        else:
            prev = fast.get("previousClose") or fast.get("regularMarketPreviousClose")

        if last is None:
            return Result(
                name=name,
                ticker=yf_ticker,
                price=None,
                change_pct=None,
                volume=None,
                source="failed",
                error="yfinance 返回空价格",
            )

        chg = ((last - prev) / prev * 100) if prev and prev > 0 else None

        return Result(
            name=name,
            ticker=yf_ticker,
            price=round(float(last), 4),
            change_pct=round(float(chg), 2) if chg is not None else None,
            volume=None,
            source="yfinance (雅虎)",
            error="",
        )
    except Exception as e:
        return Result(
            name=name,
            ticker=yf_ticker or "N/A",
            price=None,
            change_pct=None,
            volume=None,
            source="failed",
            error=str(e)[:120],
        )


def print_header():
    print("=" * 90)
    print("  🔬 Quant Agent — 宏观数据源连通性验证")
    print(f"  🕒 执行时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
    print("=" * 90)


def print_result(r: Result):
    """格式化输出单条结果"""
    icon = "✅" if r.ok() else "❌"
    price_str = f"{r.price:,.2f}" if r.price is not None else "—"
    chg_str = f"{r.change_pct:+.2f}%" if r.change_pct is not None else "—"
    vol_str = r.volume or "—"

    print(f"  {icon} {r.name:<20s} | 价格: {price_str:>12s} | 涨跌: {chg_str:>8s}  | 成交量: {vol_str:>10s} | 来源: {r.source}")
    if r.error:
        print(f"     ⚠️  错误: {r.error}")


def main():
    print_header()

    # ── 阶段 1: 连接 Futu OpenD ──────────────────────────────────────
    print("\n📡 [阶段 1] 尝试连接 Futu OpenD (127.0.0.1:11111)...")
    quote_ctx = None
    futu_ok = False

    try:
        quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        # 简单连通性检查: 尝试获取恒生指数快照
        ret, _ = quote_ctx.get_market_snapshot(["HK.800000"])
        if ret == RET_OK:
            futu_ok = True
            print("  ✅ Futu OpenD 连接成功，将优先使用富途数据源。\n")
        else:
            print("  ⚠️  Futu OpenD 连接成功但快照获取失败，将全部降级至 yfinance。\n")
    except Exception as e:
        print(f"  ❌ Futu OpenD 连接失败: {e}")
        print("     所有标的将使用 Yahoo Finance 作为数据源。\n")

    # ── 阶段 2: 逐个验证 ─────────────────────────────────────────────
    print("📊 [阶段 2] 逐标的数据获取验证\n")
    print(f"  {'标的':<20s} | {'价格':>12s} | {'涨跌':>8s}  | {'成交量':>10s} | 来源")
    print("  " + "-" * 85)

    results: list[Result] = []
    futu_success = 0
    yf_success = 0
    total_failed = 0

    for name, futu_code, yf_code, kind in TARGETS:
        result = None

        # 优先尝试富途
        if futu_ok and futu_code and quote_ctx:
            result = try_futu(quote_ctx, futu_code)
            if result:
                result.name = name
                # 二次确认：如果富途返回价格为 0 也视为无效
                if result.price and result.price > 0:
                    futu_success += 1
                    results.append(result)
                    print_result(result)
                    continue
                else:
                    result = None  # 价格为0，降级

        # 富途失败 → 降级到 yfinance
        tag = f"[{kind}]"
        print(f"  ⏳ {name:<20s} | {tag:<10s} 富途不支持/失败，降级至 yfinance ...")
        result = try_yfinance(name, yf_code)
        if result.ok():
            yf_success += 1
        else:
            total_failed += 1
        results.append(result)
        print_result(result)

    # ── 清理 ─────────────────────────────────────────────────────────
    if quote_ctx:
        quote_ctx.close()

    # ── 阶段 3: 汇总 ─────────────────────────────────────────────────
    total = len(TARGETS)
    print("\n" + "=" * 90)
    print("  📋 验证汇总")
    print("=" * 90)
    print(f"  总计标的: {total}")
    print(f"  ✅ 成功 (富途): {futu_success}")
    print(f"  ✅ 成功 (雅虎): {yf_success}")
    print(f"  ❌ 失败:       {total_failed}")
    print(f"  📊 成功率:     {(futu_success + yf_success) / total * 100:.1f}%")
    print(f"\n  数据获取时间: {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())}")
    print(f"  数据来源:     futu_fetch.py (Futu OpenD / yfinance)")

    # 返回非零退出码便于 CI 判断
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())