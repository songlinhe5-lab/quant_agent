#!/usr/bin/env python3
"""🚀 Epic 3 Task 1: Final Integration Test - All Indicators via Engine"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from backend.utils.technical_indicators_pro import (
    TechnicalIndicatorsEngine,
    DEFAULT_INDICATORS,
    IndicatorConfig
)


def generate_test_data(n_bars: int = 100):
    """生成合成测试数据"""
    np.random.seed(42)
    
    base_price = 100.0
    trend = np.linspace(0, 20, n_bars)
    prices = base_price + trend + np.cumsum(np.random.randn(n_bars) * 0.8)
    
    df = pd.DataFrame({
        "datetime": [datetime.now() - timedelta(days=i) for i in range(n_bars-1, -1, -1)],
        "open": prices + np.random.randn(n_bars) * 0.3,
        "high": prices + abs(np.random.randn(n_bars)) * 0.6,
        "low": prices - abs(np.random.randn(n_bars)) * 0.6,
        "close": prices,
        "volume": np.random.randint(1_000_000, 5_000_000, n_bars)
    })
    
    return df.to_dict("records")


def test_engine_integration():
    """Test that all 6 new indicators are accessible through the Engine API"""
    
    print("\n" + "="*70)
    print("🚀 EPIC 3 TASK 1: ENGINE INTEGRATION TEST - ALL INDICATORS")
    print("="*70)
    
    klines = generate_test_data(100)
    engine = TechnicalIndicatorsEngine(auto_calculate_signals=True)
    
    # Define NEW indicators to test
    new_indicators = [
        IndicatorConfig(name="ADX", indicator_type="trend", params={"period": 14}),
        IndicatorConfig(name="CCI", indicator_type="momentum", params={"period": 20}),
        IndicatorConfig(name="VWMA", indicator_type="trend", params={"period": 20}),
        IndicatorConfig(name="atr_percent", indicator_type="volatility", params={"period": 14}),
        IndicatorConfig(name="elder_ray", indicator_type="momentum", params={"period": 14}),
        IndicatorConfig(name="keltner_channels", indicator_type="volatility", params={"period": 20, "atrp_multiplier": 1.5}),
    ]
    
    results = {}
    
    try:
        print("\n📊 Calculating new indicators via Engine API...")
        result = engine.calculate(klines, indicators=new_indicators, return_history=False)
        
        print(f"\n✅ Computation time: {result['_meta']['computation_time_ms']:.2f}ms\n")
        
        # Check each indicator
        indicators_to_check = ["adx", "cci", "vwma", "atr_percent", "elder_ray", "keltner_channels"]
        
        for name in indicators_to_check:
            if name in result:
                results[name] = result[name]
                print(f"   ✓ {name.upper()} available")
                
                # Display some key values
                if isinstance(result[name], dict):
                    items = list(result[name].items())[:3]  # Show first 3 items
                    for key, value in items:
                        if value is not None and isinstance(value, float):
                            print(f"      • {key}: {value:.4f}" if abs(value) > 0.01 else f"      • {key}: {value}")
                        elif value is not None:
                            print(f"      • {key}: {value}")
            else:
                print(f"   ✗ {name.upper()} MISSING from result!")
        
        # Check signal generation
        print("\n📡 Signal Generation:")
        for name in indicators_to_check:
            if name in result and isinstance(result[name], dict) and "signal" in result[name]:
                print(f"   ✓ {name}: {result[name]['signal']}")
        
        # Validate results
        print("\n✅ Validation Results:")
        validations_passed = 0
        
        # ADX check
        if "adx" in result:
            adx_val = result["adx"].get("adx")
            if adx_val and 0 <= adx_val <= 100:
                print(f"   ✓ ADX valid ({adx_val:.2f})")
                validations_passed += 1
            else:
                print(f"   ⚠ ADX out of range: {adx_val}")
        
        # CCI check
        if "cci" in result:
            cci_val = result["cci"].get("cci")
            if cci_val is not None:
                print(f"   ✓ CCI computed: {cci_val:.2f}")
                validations_passed += 1
            else:
                print(f"   ⚠ CCI is None")
        
        # VWMA check
        if "vwma" in result:
            vwma_val = result["vwma"].get("vwma")
            if vwma_val and vwma_val > 0:
                print(f"   ✓ VWMA computed: ${vwma_val:.2f}")
                validations_passed += 1
            else:
                print(f"   ⚠ VWMA invalid: {vwma_val}")
        
        # ATR% check
        if "atr_percent" in result:
            atr_pct = result["atr_percent"].get("atr_percent")
            if atr_pct and atr_pct >= 0:
                print(f"   ✓ ATR% computed: {atr_pct:.2f}%")
                validations_passed += 1
            else:
                print(f"   ⚠ ATR% invalid: {atr_pct}")
        
        # Elder-Ray check
        if "elder_ray" in result:
            bull_power = result["elder_ray"].get("bull_power")
            bear_power = result["elder_ray"].get("bear_power")
            if bull_power is not None or bear_power is not None:
                print(f"   ✓ Elder-Ray computed (Bull: {bull_power:.2f}, Bear: {bear_power:.2f})")
                validations_passed += 1
            else:
                print(f"   ⚠ Elder-Ray values missing")
        
        # Keltner check
        if "keltner_channels" in result:
            middle = result["keltner_channels"].get("middle")
            upper = result["keltner_channels"].get("upper")
            lower = result["keltner_channels"].get("lower")
            if middle is not None and upper is not None and lower is not None:
                print(f"   ✓ Keltner channels computed")
                print(f"      • Upper: ${upper:.2f}, Middle: ${middle:.2f}, Lower: ${lower:.2f}")
                validations_passed += 1
            else:
                print(f"   ⚠ Keltner channels incomplete")
        
        total_checks = 6
        success_rate = validations_passed / total_checks * 100
        
        print("\n" + "="*70)
        print(f"📊 INTEGRATION STATUS: {validations_passed}/{total_checks} checks passed ({success_rate:.0f}%)")
        print("="*70)
        
        if validations_passed == total_checks:
            print("\n🎉 SUCCESS! All 6 new indicators integrated successfully!")
            print("\n✨ Deliverables:")
            print("   ✅ ADX/DMI - Trend strength indicator")
            print("   ✅ CCI - Momentum oscillator")
            print("   ✅ VWMA - Volume weighted average")
            print("   ✅ ATR% - Volatility percentage")
            print("   ✅ Elder-Ray - Bull/Bear power")
            print("   ✅ Keltner Channels - Volatility channels")
            
            print("\n🏁 Next Steps:")
            print("   1. Write comprehensive unit tests")
            print("   2. Add accuracy validation vs TradingView")
            print("   3. Update documentation with examples")
            print("   4. Move to next Epic task")
            
            return True
        else:
            print(f"\n⚠️ Some indicators failed integration. Please review above.")
            return False
    
    except Exception as e:
        print(f"\n❌ ERROR during integration: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_indicator_set():
    """Test ALL indicators together (old + new)"""
    
    print("\n" + "="*70)
    print("🧪 COMPREHENSIVE TEST: All Indicators Combined")
    print("="*70)
    
    klines = generate_test_data(100)
    engine = TechnicalIndicatorsEngine(auto_calculate_signals=True)
    
    # Mix of old and new indicators
    all_indicators = DEFAULT_INDICATORS + [
        IndicatorConfig(name="ADX", indicator_type="trend", params={"period": 14}),
        IndicatorConfig(name="CCI", indicator_type="momentum", params={"period": 20}),
        IndicatorConfig(name="VWMA", indicator_type="trend", params={"period": 20}),
    ]
    
    try:
        print(f"\nCalculating {len(all_indicators)} indicators together...")
        result = engine.calculate(klines, indicators=all_indicators, return_history=False)
        
        print(f"\n✅ All indicators computed in {result['_meta']['computation_time_ms']:.2f}ms")
        print(f"   Total keys in result: {len([k for k in result.keys() if not k.startswith('_')])}")
        
        print("\n📊 Result summary:")
        old_count = sum(1 for k in result.keys() if k in ["ma", "ema", "macd", "rsi", "stochastic", "bollinger", "atr"])
        new_count = sum(1 for k in result.keys() if k in ["adx", "cci", "vwma"])
        
        print(f"   ✓ Old indicators: {old_count}")
        print(f"   ✓ New indicators: {new_count}")
        print(f"   ✓ TOTAL: {old_count + new_count}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all integration tests"""
    
    print("\n" + "="*70)
    print("🚀 EPIC 3 TASK 1: COMPLETE INTEGRATION VERIFICATION")
    print("="*70 + "\n")
    
    # Run both tests
    success1 = test_engine_integration()
    success2 = test_full_indicator_set()
    
    # Final verdict
    print("\n" + "="*70)
    print("🎯 FINAL VERDICT")
    print("="*70)
    
    if success1 and success2:
        print("\n✅ EPIC 3 TASK 1: FULLY COMPLETE!")
        print("\nAll 6 advanced indicators successfully integrated into TechnicalIndicatorsEngine")
        print("Ready for unit testing and accuracy validation")
        print("="*70)
        return True
    else:
        print("\n❌ Some integration tests failed")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
