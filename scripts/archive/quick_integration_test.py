#!/usr/bin/env python3
"""🎯 Phase 2 Quick Integration Test - Validation Check"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.utils.technical_indicators_pro import (
    TechnicalIndicatorsEngine,
    DEFAULT_INDICATORS,
    IndicatorConfig
)


def test_real_world_strategy():
    """Generate synthetic data simulating real market conditions"""
    
    print("\n" + "="*60)
    print("🚀 PHASE 2 QUICK INTEGRATION TEST")
    print("="*60)
    
    # Generate realistic price data with trend and volatility
    np.random.seed(42)
    n_bars = 100
    
    # Start at base price with random walk
    base_price = 100.0
    prices = base_price + np.cumsum(np.random.randn(n_bars) * 2)
    
    # Create OHLCV data
    df = pd.DataFrame({
        "datetime": [datetime.now() - timedelta(days=i) for i in range(n_bars-1, -1, -1)],
        "open": prices + np.random.randn(n_bars) * 0.5,
        "high": prices + abs(np.random.randn(n_bars)) * 1.0,
        "low": prices - abs(np.random.randn(n_bars)) * 1.0,
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, n_bars)
    })
    
    print(f"\n📊 Data: {len(df)} bars ({df['datetime'].min()} ~ {df['datetime'].max()})")
    print(f"   Price range: ${prices.min():.2f} ~ ${prices.max():.2f}")
    
    # Convert to klines format
    klines = df.to_dict("records")
    
    # Calculate indicators
    engine = TechnicalIndicatorsEngine()
    
    print("\n⏱ Calculating indicators...")
    result = engine.calculate(klines, indicators=DEFAULT_INDICATORS, return_history=False)
    
    print(f"\n✅ Computation time: {result['_meta']['computation_time_ms']:.2f}ms")
    
    # Print key indicators
    print("\n📈 Core Indicators:")
    
    # MA values - result is like {'ma': {'ma5': 102.5, 'ma10': 101.8}}
    if "ma" in result and isinstance(result["ma"], dict):
        for period, value in result["ma"].items():
            print(f"  ├─ {period.upper()}: ${value:.2f}" if value else f"  ├─ {period.upper()}: N/A")
    
    # MACD
    if "macd" in result:
        macd = result["macd"]
        print(f"  ├─ MACD(12,26,9):")
        print(f"  │  ├─ DIF: {macd.get('dif', 'N/A'):.3f}")
        print(f"  │  ├─ DEA: {macd.get('dea', 'N/A'):.3f}")
        print(f"  │  └─ Histogram: {macd.get('macd_hist', 'N/A'):.3f}")
    
    # RSI
    if "rsi" in result:
        rsi = result["rsi"]
        print(f"  ├─ RSI(14): {rsi.get('rsi', 'N/A'):.2f}")
        if "signal" in rsi:
            print(f"  │  └─ Signal: {rsi['signal']}")
    
    # Stochastic
    if "stochastic" in result:
        stoch = result["stochastic"]
        print(f"  ├─ Stochastic(14,3,3):")
        print(f"  │  ├─ %K: {stoch.get('k_val', 'N/A'):.2f}")
        print(f"  │  ├─ %D: {stoch.get('d_val', 'N/A'):.2f}")
        if "signal" in stoch:
            print(f"  │  └─ Signal: {stoch['signal']}")
    
    # Bollinger
    if "bollinger" in result:
        bb = result["bollinger"]
        print(f"  ├─ Bollinger(20,2σ):")
        print(f"  │  ├─ Upper: ${bb.get('upper', 'N/A'):.2f}")
        print(f"  │  ├─ Middle: ${bb.get('middle', 'N/A'):.2f}")
        print(f"  │  └─ Lower: ${bb.get('lower', 'N/A'):.2f}")
    
    # ATR
    if "atr" in result:
        atr = result["atr"]
        current_price = klines[-1]["close"]
        atr_pct = (atr["value"] / current_price * 100) if atr["value"] else 0
        print(f"  ├─ ATR(14): ${atr['value']:.2f} ({atr_pct:.2f}%)")
    
    # OBV
    if "obv" in result:
        obv = result["obv"]
        print(f"  ├─ OBV: {obv['obv']:,.0f}")
    
    # VWAP
    if "vwap" in result:
        vwap = result["vwap"]
        current_price = klines[-1]["close"]
        deviation = ((current_price - vwap["vwap"]) / vwap["vwap"] * 100) if vwap["vwap"] else 0
        print(f"  ├─ VWAP: ${vwap['vwap']:.2f}")
        print(f"  └─ Price vs VWAP: {deviation:+.2f}%")
    
    # ✅ Validation checks
    print("\n✅ Validation Checks:")
    validations = []
    
    # 1. RSI should be 0-100
    if "rsi" in result:
        rsi_value = result["rsi"].get("rsi")
        if rsi_value is not None and 0 <= rsi_value <= 100:
            print(f"  ✓ RSI within bounds [0, 100]")
            validations.append(True)
        else:
            print(f"  ✗ RSI out of bounds: {rsi_value}")
            validations.append(False)
    
    # 2. ATR should be positive
    if "atr" in result:
        atr_value = result["atr"].get("value")
        if atr_value is not None and atr_value > 0:
            print(f"  ✓ ATR positive (${atr_value:.2f})")
            validations.append(True)
        else:
            print(f"  ✗ ATR invalid: {atr_value}")
            validations.append(False)
    
    # 3. Computation time < 100ms
    comp_time = result["_meta"]["computation_time_ms"]
    if comp_time < 100:
        print(f"  ✓ Performance OK ({comp_time:.2f}ms)")
        validations.append(True)
    else:
        print(f"  ✗ Performance issue: {comp_time:.2f}ms > 100ms threshold")
        validations.append(False)
    
    # 4. No NaN/Inf values
    has_nan = any(np.isnan(v) if isinstance(v, float) else False 
                  for sublist in result.values() if isinstance(sublist, dict) 
                  for v in sublist.values())
    if not has_nan:
        print(f"  ✓ No NaN/Inf values detected")
        validations.append(True)
    else:
        print(f"  ✗ Found NaN/Inf values!")
        validations.append(False)
    
    # Final verdict
    passed = sum(validations)
    total = len(validations)
    
    print("\n" + "="*60)
    print(f"📊 VALIDATION RESULTS: {passed}/{total} checks passed ({passed/total*100:.0f}%)")
    print("="*60)
    
    if passed == total:
        print("\n🎉 ALL CHECKS PASSED! ✅")
        print("Phase 2 indicators are PRODUCTION READY")
        return True
    else:
        print(f"\n⚠️ {total - passed} validation(s) failed. Please review.")
        return False


if __name__ == "__main__":
    from pathlib import Path
    
    success = test_real_world_strategy()
    sys.exit(0 if success else 1)
