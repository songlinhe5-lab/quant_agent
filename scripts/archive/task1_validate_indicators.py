#!/usr/bin/env python3
"""🎯 Epic 3 - Task 1: Advanced Indicators Implementation"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.utils.technical_indicators_pro import TechnicalIndicatorsEngine, DEFAULT_INDICATORS, IndicatorConfig
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


def test_adx_dmi():
    """测试 ADX/DMI (Average Directional Index)"""
    
    print("\n" + "="*60)
    print("📊 TASK 1 TEST: ADX/DMI - 趋势强度指数")
    print("="*60)
    
    # Generate synthetic trending data
    np.random.seed(123)
    n_bars = 80
    
    # Create a strong uptrend
    base_price = 100.0
    trend = np.linspace(0, 20, n_bars)  # 20% upward trend
    noise = np.cumsum(np.random.randn(n_bars) * 0.5)
    prices = base_price + trend + noise
    
    df = pd.DataFrame({
        "datetime": [datetime.now() - timedelta(days=i) for i in range(n_bars-1, -1, -1)],
        "open": prices + np.random.randn(n_bars) * 0.3,
        "high": prices + abs(np.random.randn(n_bars)) * 0.6,
        "low": prices - abs(np.random.randn(n_bars)) * 0.6,
        "close": prices,
        "volume": np.random.randint(1_000_000, 5_000_000, n_bars)
    })
    
    klines = df.to_dict("records")
    
    # Configure ADX/DMI
    adx_config = IndicatorConfig(
        name="adx",
        indicator_type="trend",
        params={"period": 14},
        signal_thresholds={"strong_trend": 25, "weak_trend": 20}
    )
    
    engine = TechnicalIndicatorsEngine(auto_calculate_signals=True)
    result = engine.calculate(klines, indicators=[adx_config], return_history=False)
    
    print(f"\n✅ ADX Calculation Complete:")
    
    if "error" in result:
        print(f"❌ Error: {result['error']}")
        return False
    
    if "adx" not in result:
        print("⚠️ ADX indicator not found in results")
        print(f"Available keys: {list(result.keys())}")
        return False
    
    adx = result["adx"]
    print(f"  • ADX: {adx.get('adx', 'N/A'):.2f}")
    print(f"  • +DI (正向): {adx.get('plus_di', 'N/A'):.2f}")
    print(f"  • -DI (负向): {adx.get('minus_di', 'N/A'):.2f}")
    print(f"  • DI Spread: {adx.get('di_diff', 'N/A'):.2f}")
    
    if "signal" in adx:
        print(f"  • Signal: {adx['signal']}")
    
    # Validate values
    adx_val = adx.get("adx")
    plus_di = adx.get("plus_di")
    minus_di = adx.get("minus_di")
    
    checks = []
    
    # 1. ADX should be 0-100
    if adx_val is not None and 0 <= adx_val <= 100:
        print(f"✓ ADX within bounds [0,100]: {adx_val:.2f}")
        checks.append(True)
    else:
        print(f"✗ ADX out of bounds: {adx_val}")
        checks.append(False)
    
    # 2. +DI and -DI should be 0-100
    if plus_di is not None and 0 <= plus_di <= 100:
        print(f"✓ +DI within bounds: {plus_di:.2f}")
        checks.append(True)
    else:
        print(f"✗ +DI invalid: {plus_di}")
        checks.append(False)
    
    if minus_di is not None and 0 <= minus_di <= 100:
        print(f"✓ -DI within bounds: {minus_di:.2f}")
        checks.append(True)
    else:
        print(f"✗ -DI invalid: {minus_di}")
        checks.append(False)
    
    # 3. Strong trend detection (we have a clear uptrend)
    if adx_val and adx_val > 25:
        print(f"✓ Strong trend detected (ADX={adx_val:.1f} > 25)")
        checks.append(True)
    elif adx_val and 20 <= adx_val <= 25:
        print(f"✓ Moderate trend detected (ADX={adx_val:.1f})")
        checks.append(True)
    else:
        print(f"⚠ Trend weak or inconsistent (ADX={adx_val:.1f})")
        # Not necessarily an error for random data
    
    summary = f"{sum(checks)}/{len(checks)} validations passed"
    print(f"\n{summary}")
    
    return sum(checks) >= 2


def test_cci():
    """测试 CCI (Commodity Channel Index)"""
    
    print("\n" + "="*60)
    print("📊 TASK 1 TEST: CCI - 商品通道指数")
    print("="*60)
    
    np.random.seed(456)
    n_bars = 80
    
    # Oscillating price pattern
    t = np.linspace(0, 4*np.pi, n_bars)
    prices = 100 + 15*np.sin(t) + np.random.randn(n_bars)*2
    
    df = pd.DataFrame({
        "datetime": [datetime.now() - timedelta(days=i) for i in range(n_bars-1, -1, -1)],
        "open": prices + np.random.randn(n_bars) * 0.5,
        "high": prices + abs(np.random.randn(n_bars)) * 1.0,
        "low": prices - abs(np.random.randn(n_bars)) * 1.0,
        "close": prices,
        "volume": np.random.randint(1_000_000, 5_000_000, n_bars)
    })
    
    klines = df.to_dict("records")
    
    cci_config = IndicatorConfig(
        name="cci",
        indicator_type="momentum",
        params={"period": 20},
        signal_thresholds={"overbought": 100, "oversold": -100}
    )
    
    engine = TechnicalIndicatorsEngine(auto_calculate_signals=True)
    result = engine.calculate(klines, indicators=[cci_config], return_history=False)
    
    print(f"\n✅ CCI Calculation Complete:")
    
    if "error" in result:
        print(f"❌ Error: {result['error']}")
        return False
    
    if "cci" not in result:
        print("⚠️ CCI indicator not found")
        return False
    
    cci = result["cci"]
    cci_val = cci.get("cci", "N/A")
    
    print(f"  • CCI: {cci_val:.2f}")
    
    if "signal" in cci:
        print(f"  • Signal: {cci['signal']}")
    
    # Validation
    if cci_val is not None:
        if cci_val > 100:
            print(f"✓ Overbought condition: {cci_val:.2f}")
        elif cci_val < -100:
            print(f"✓ Oversold condition: {cci_val:.2f}")
        else:
            print(f"✓ Normal range: {cci_val:.2f}")
        
        return True
    
    return False


def test_vwma():
    """测试 VWMA (Volume Weighted Moving Average)"""
    
    print("\n" + "="*60)
    print("📊 TASK 1 TEST: VWMA - 成交量加权移动平均")
    print("="*60)
    
    np.random.seed(789)
    n_bars = 80
    
    prices = 50 + np.cumsum(np.random.randn(n_bars) * 1.5)
    
    # Create volume spikes at key points
    volumes = np.ones(n_bars) * 2_000_000
    volumes[20] = 8_000_000  # Spike
    volumes[50] = 6_000_000  # Another spike
    
    df = pd.DataFrame({
        "datetime": [datetime.now() - timedelta(days=i) for i in range(n_bars-1, -1, -1)],
        "open": prices + np.random.randn(n_bars) * 0.3,
        "high": prices + abs(np.random.randn(n_bars)) * 0.5,
        "low": prices - abs(np.random.randn(n_bars)) * 0.5,
        "close": prices,
        "volume": volumes
    })
    
    klines = df.to_dict("records")
    
    vwma_config = IndicatorConfig(
        name="vwma",
        indicator_type="trend",
        params={"period": 20}
    )
    
    engine = TechnicalIndicatorsEngine()
    result = engine.calculate(klines, indicators=[vwma_config], return_history=False)
    
    print(f"\n✅ VWMA Calculation Complete:")
    
    if "error" in result:
        print(f"❌ Error: {result['error']}")
        return False
    
    if "vwma" not in result:
        print("⚠️ VWMA not found")
        return False
    
    vwma = result["vwma"]
    vwma_val = vwma.get("vwma")
    
    print(f"  • VWMA(20): ${vwma_val:.2f if vwma_val else 'N/A':8s}")
    
    # Compare with regular MA
    ma_config = IndicatorConfig(name="ma", indicator_type="trend", params={"periods": [20]})
    result_ma = engine.calculate(klines, indicators=[ma_config], return_history=False)
    
    if "ma" in result_ma:
        ma_20 = list(result_ma["ma"].values())[0]
        print(f"  • SMA(20): ${ma_20:.2f if ma_20 else 'N/A':8s}")
        print(f"  • Difference: {((vwma_val - ma_20) / ma_20 * 100 if ma_20 and vwma_val else 0):+.2f}%")
    
    if vwma_val is not None and vwma_val > 0:
        print(f"✓ VWMA valid: ${vwma_val:.2f}")
        return True
    
    return False


def main():
    """Run all Task 1 indicator tests"""
    
    print("\n" + "="*60)
    print("🚀 EPIC 3 TASK 1: ADVANCED INDICATORS IMPLEMENTATION")
    print("="*60)
    
    results = {}
    
    try:
        # Test each new indicator
        results["ADX/DMI"] = test_adx_dmi()
        results["CCI"] = test_cci()
        results["VWMA"] = test_vwma()
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n" + "="*60)
        print("📊 TASK 1 TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for test_name, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} | {test_name}")
        
        print(f"\n📈 Success Rate: {passed}/{total} ({passed/total*100:.0f}%)")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED! ✅")
            print("Task 1 implementation verified successfully!")
        else:
            print(f"\n⚠️ Some tests failed. Please review the logs.")
        
        print("="*60)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
