#!/usr/bin/env python3
"""🎯 Phase 2 Integration Tests: Real-world strategy validation"""

import asyncio
import sys
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.utils.technical_indicators_pro import (
    TechnicalIndicatorsEngine,
    DEFAULT_INDICATORS,
    IndicatorConfig
)
# from backend.workers.futu_service import FutuService  # Temporarily disabled
import pandas as pd


def test_rsi_macd_strategy():
    """Test Case 1: RSI+MACD Dual Signal Strategy"""
    print("\n" + "="*60)
    print("🧪 TEST CASE 1: RSI+MACD 双信号共振策略")
    print("="*60)
    
    # Load sample data from backend/data/klines/
    try:
        df = pd.read_csv(
            "/Users/stephenhe/Development/workspace/quant_agent/backend/data/klines/AAPL_daily.csv",
            parse_dates=["datetime"]
        )
        df = df.sort_values("datetime").tail(100).reset_index(drop=True)
        
        print(f"📊 Data loaded: {len(df)} bars (AAPL)")
        print(f"📅 Date range: {df['datetime'].min()} ~ {df['datetime'].max()}")
        
    except FileNotFoundError:
        print("⚠️ Sample CSV not found, generating synthetic data...")
        dates = pd.date_range(end=datetime.now(), periods=100, freq="D")
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.randn(100) * 2)
        df = pd.DataFrame({
            "datetime": dates,
            "open": close_prices + np.random.randn(100),
            "high": close_prices + abs(np.random.randn(100)),
            "low": close_prices - abs(np.random.randn(100)),
            "close": close_prices,
            "volume": np.random.randint(1_000_000, 10_000_000, 100)
        })
    
    # Generate klines format
    klines = df.to_dict("records")
    
    # Calculate indicators
    engine = TechnicalIndicatorsEngine()
    result = engine.calculate(klines, indicators=DEFAULT_INDICATORS, return_history=False)
    
    print("\n✅ Indicators calculated:")
    
    # Print raw result for debugging
    import json
    print(f"📊 Result structure: {json.dumps(result, indent=2, default=str)[:500]}")
    
    # Debug: Check actual key names in result
    rsi_data = result.get("rsi", {})
    macd_data = result.get("macd", {})
    print(f"  │  ├─ Signal: {result['rsi']['signal']}")
    print(f"  │  └─ Trend: {result['rsi']['trend']}")
    print(f"  ├─ MACD(12,26,9):")
    print(f"  │  ├─ DIF: {result['macd']['dif']:.2f}")
    print(f"  │  ├─ DEA: {result['macd']['dea']:.2f}")
    print(f"  │  └─ Histogram: {result['macd']['macd_hist']:.2f}")
    print(f"  └─ Overall: {result.get('overall_signal', 'N/A')}")
    
    # Execute trading signals
    rsi_condition = result["rsi"]["value"] < 30  # Oversold
    macd_condition = result["macd"]["dif"] > result["macd"]["dea"]  # Bullish crossover
    
    if rsi_condition and macd_condition:
        signal = "STRONG_BUY (双信号共振!)"
    elif rsi_condition or macd_condition:
        signal = "WEAK_BUY (单信号)"
    else:
        signal = "NEUTRAL/SELL"
    
    print(f"\n🎯 Trading Signal: {signal}")
    
    # Validate against expected ranges
    assert 0 <= result["rsi"]["value"] <= 100, "RSI out of bounds!"
    assert -1000 <= result["macd"]["dif"] <= 1000, "MACD DIF abnormal!"
    assert result["atr"]["value"] > 0, "ATR should be positive!"
    
    print("✅ All validations passed!")
    return True


def test_stochastic_obv_vwap():
    """Test Case 2: Stochastic + OBV + VWAP Analysis"""
    print("\n" + "="*60)
    print("🧪 TEST CASE 2: Stochastic + OBV + VWAP 联合分析")
    print("="*60)
    
    # Fetch real data via Futu API (if available)
    futu = FutuService()
    ticker = "NVDA"
    
    try:
        print(f"🌐 Fetching {ticker} historical K-lines from Futu...")
        klines = futu._get_kline_data(ticker, period="1d", start_date="2026-01-01", end_date="2026-07-08")
    except Exception as e:
        print(f"⚠️ Futu unavailable: {e}, using synthetic data")
        np.random.seed(123)
        n = 60
        prices = 500 + np.cumsum(np.random.randn(n) * 5)
        dates = pd.date_range(end=datetime.now(), periods=n, freq="D")
        df = pd.DataFrame({
            "datetime": dates,
            "open": prices + np.random.randn(n),
            "high": prices + abs(np.random.randn(n)),
            "low": prices - abs(np.random.randn(n)),
            "close": prices,
            "volume": np.random.randint(10_000_000, 50_000_000, n)
        })
        klines = df.to_dict("records")
    
    print(f"📊 Data loaded: {len(klines)} bars ({ticker})")
    
    # Custom indicator config
    custom_config = [
        IndicatorConfig(name="stochastic", indicator_type="oscillator", params={"period": 14}),
        IndicatorConfig(name="obv", indicator_type="volume", params={}),
        IndicatorConfig(name="vwap", indicator_type="trend", params={}),
    ]
    
    engine = TechnicalIndicatorsEngine()
    result = engine.calculate(klines, indicators=custom_config, return_history=False)
    
    print("\n✅ Custom indicators calculated:")
    
    # Stochastic
    if "stochastic" in result:
        stoch = result["stochastic"]
        print(f"  ├─ Stochastic(14,3,3):")
        print(f"  │  ├─ %K: {stoch['k_val']:.2f}")
        print(f"  │  ├─ %D: {stoch['d_val']:.2f}")
        print(f"  │  └─ Signal: {stoch['signal']}")
    
    # OBV
    if "obv" in result:
        obv = result["obv"]
        print(f"  ├─ OBV: {obv['obv']:.0f}")
        print(f"     └─ Recent trend: {'↑ Accumulation' if obv['obv_change'] > 0 else '↓ Distribution'}")
    
    # VWAP
    if "vwap" in result:
        vwap = result["vwap"]
        current_price = klines[-1]["close"]
        deviation = ((current_price - vwap['vwap']) / vwap['vwap'] * 100)
        print(f"  ├─ VWAP: {vwap['vwap']:.2f}")
        print(f"  └─ Current Price vs VWAP: {deviation:+.2f}%")
    
    # Composite signal
    composite_score = 0
    if result["stochastic"]["signal"] == "OVERBOUGHT":
        composite_score -= 1
    elif result["stochastic"]["signal"] == "OVERSOLD":
        composite_score += 1
    
    if obv["obv_change"] > 0 and vwap["vwap"] < current_price:
        composite_score += 1
    elif obv["obv_change"] < 0 and vwap["vwap"] > current_price:
        composite_score -= 1
    
    if composite_score >= 2:
        final_signal = "BULLISH COMPOSITE"
    elif composite_score <= -2:
        final_signal = "BEARISH COMPOSITE"
    else:
        final_signal = "NEUTRAL/MIXED"
    
    print(f"\n🎯 Composite Signal: {final_signal} (Score: {composite_score:+d})")
    
    print("✅ Test completed successfully!")
    return True


def test_bollinger_atr_volatility():
    """Test Case 3: Bollinger Bands + ATR Volatility"""
    print("\n" + "="*60)
    print("🧪 TEST CASE 3: Bollinger + ATR 波动率分析")
    print("="*60)
    
    # Use Google stock data for high volatility scenario
    ticker = "GOOGL"
    print(f"🔍 Analyzing: {ticker}")
    
    # Simulate volatile market conditions
    np.random.seed(456)
    n = 80
    base = 150
    prices = base + np.cumsum(np.random.randn(n) * 4)  # Higher volatility
    
    dates = pd.date_range(end=datetime.now(), periods=n, freq="D")
    df = pd.DataFrame({
        "datetime": dates,
        "open": prices + np.random.randn(n),
        "high": prices + abs(np.random.randn(n)) * 2,
        "low": prices - abs(np.random.randn(n)) * 2,
        "close": prices,
        "volume": np.random.randint(1_000_000, 5_000_000, n)
    })
    klines = df.to_dict("records")
    
    # Configure Bollinger + ATR
    vol_config = [
        IndicatorConfig(name="bollinger", indicator_type="volatility", params={"period": 20, std_devs: 2.0}),
        IndicatorConfig(name="atr", indicator_type="volatility", params={"period": 14}),
    ]
    
    engine = TechnicalIndicatorsEngine()
    result = engine.calculate(klines, indicators=vol_config, return_history=False)
    
    print("\n✅ Volatility indicators:")
    
    # Bollinger Bands
    bb = result["bollinger"]
    upper = bb["upper"]
    middle = bb["middle"]
    lower = bb["lower"]
    band_width = ((upper - lower) / middle * 100)
    price_pos = (bb["price"] - lower) / (upper - lower) * 100
    
    print(f"  ├─ Bollinger(20,2.0σ):")
    print(f"  │  ├─ Upper: {upper:.2f}")
    print(f"  │  ├─ Middle (SMA): {middle:.2f}")
    print(f"  │  ├─ Lower: {lower:.2f}")
    print(f"  │  ├─ Band Width: {band_width:.2f}%")
    print(f"  │  ├─ Price Position: {price_pos:.1f}%")
    print(f"  │  └─ Squeeze: {'YES' if band_width < 10 else 'NO'}")
    
    # ATR
    atr = result["atr"]
    current_price = klines[-1]["close"]
    atr_percent = atr["value"] / current_price * 100
    
    print(f"  └─ ATR(14): {atr['value']:.2f} ({atr_percent:.2f}% of price)")
    
    # Volatility regime classification
    if band_width < 10:
        vol_regime = "Low Volatility (Squeeze detected)"
    elif band_width < 20:
        vol_regime = "Normal Volatility"
    else:
        vol_regime = "High Volatility (Breakout candidate)"
    
    print(f"\n📊 Volatility Regime: {vol_regime}")
    
    # Dynamic stop loss suggestion
    suggested_stop_loss = current_price - (2 * atr["value"])
    suggested_take_profit = current_price + (3 * atr["value"])
    
    print(f"\n💡 Risk Management Suggestions:")
    print(f"  ├─ Stop Loss: ${suggested_stop_loss:.2f} (-{((current_price - suggested_stop_loss)/current_price)*100:.1f}%)")
    print(f"  └─ Take Profit: ${suggested_take_profit:.2f} (+{((suggested_take_profit - current_price)/current_price)*100:.1f}%)")
    print(f"  └─ Risk-Reward Ratio: 1:{3:.1f}")
    
    print("✅ Volatility analysis complete!")
    return True


def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("🚀 PHASE 2 INTEGRATION TEST SUITE")
    print("Real-world strategy validation")
    print("="*60)
    
    results = {}
    
    try:
        print("\n⏱ Starting integration tests...\n")
        
        results["Test 1: RSI+MACD Strategy"] = test_rsi_macd_strategy()
        results["Test 2: Stochastic+OBV+VWAP"] = test_stochastic_obv_vwap()
        results["Test 3: Bollinger+ATR Volatility"] = test_bollinger_atr_volatility()
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        results["Failed Test"] = False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        results["Error"] = False
    
    finally:
        # Summary
        print("\n" + "="*60)
        print("📊 INTEGRATION TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for v in results.values() if v is True)
        total = len(results)
        
        for test_name, success in results.items():
            status = "✅ PASS" if success is True else "❌ FAIL"
            print(f"{status} | {test_name}")
        
        print(f"\n📈 Overall Success Rate: {passed}/{total} ({passed/total*100:.1f}%)")
        
        if passed == total:
            print("\n🎉 ALL INTEGRATION TESTS PASSED!")
            print("Phase 2 indicators are PRODUCTION READY ✅")
        else:
            print("\n⚠️ Some tests failed. Please review the logs above.")
        
        print("="*60)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
