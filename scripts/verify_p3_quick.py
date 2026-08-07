#!/usr/bin/env python3
"""
P3 架构变更本地快速验证脚本
===========================
用法: python scripts/verify_p3_quick.py

验证内容:
1. YFinanceRouter 已完全删除
2. Facade insider 方法存在
3. format_ticker 收口到 core
4. YFinanceService 无 _router_enabled
5. Hermes Tools 可导入
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("=" * 60)
    print("🚀 P3 架构变更本地快速验证")
    print("=" * 60)
    
    checks_passed = 0
    checks_total = 0
    
    # Check 1: YFinanceRouter 文件已删除
    checks_total += 1
    router_file = Path("backend/core/yfinance_router.py")
    if not router_file.exists():
        print("✅ 1. YFinanceRouter 文件已删除")
        checks_passed += 1
    else:
        print("❌ 1. YFinanceRouter 文件仍存在")
    
    # Check 2: YFinanceRouter 无法导入
    checks_total += 1
    try:
        from backend.core.yfinance_router import YFinanceRouter
        print("❌ 2. YFinanceRouter 仍可导入")
    except ImportError:
        print("✅ 2. YFinanceRouter 无法导入 (ImportError)")
        checks_passed += 1
    
    # Check 3: format_ticker 收口到 core
    checks_total += 1
    try:
        from backend.core.ticker_format import format_ticker
        result = format_ticker("AAPL")
        assert result == "US.AAPL", f"Expected 'US.AAPL', got '{result}'"
        print(f"✅ 3. format_ticker 收口正常: 'AAPL' → '{result}'")
        checks_passed += 1
    except Exception as e:
        print(f"❌ 3. format_ticker 异常: {e}")
    
    # Check 4: Facade.get_insider_transactions 存在
    checks_total += 1
    try:
        from backend.services.datasource.business.facade import DataServiceFacade
        assert hasattr(DataServiceFacade, 'get_insider_transactions')
        print("✅ 4. Facade.get_insider_transactions 方法存在")
        checks_passed += 1
    except Exception as e:
        print(f"❌ 4. Facade 方法异常: {e}")
    
    # Check 5: YFinanceService 无 _router_enabled
    checks_total += 1
    try:
        from backend.services.yfinance.service import YFinanceService
        # 创建实例检查属性
        svc = YFinanceService.__new__(YFinanceService)
        if hasattr(svc, '_router_enabled'):
            print("❌ 5. YFinanceService 仍有 _router_enabled")
        else:
            print("✅ 5. YFinanceService 无 _router_enabled 属性")
            checks_passed += 1
    except Exception as e:
        print(f"❌ 5. YFinanceService 检查异常: {e}")
    
    # Check 6: _ensure_router 已删除
    checks_total += 1
    try:
        from backend.services.yfinance.service import YFinanceService
        if hasattr(YFinanceService, '_ensure_router'):
            print("⚠️  6. _ensure_router 方法仍存在 (可能为空方法)")
        else:
            print("✅ 6. _ensure_router 方法已删除")
            checks_passed += 1
    except Exception as e:
        print(f"❌ 6. 检查异常: {e}")
    
    # Check 7: Hermes Tools 可导入
    checks_total += 1
    try:
        from hermes_agent.tools import insider_tool, tracking_tool
        print("✅ 7. Hermes Tools (insider_tool, tracking_tool) 可导入")
        checks_passed += 1
    except Exception as e:
        print(f"❌ 7. Hermes Tools 导入异常: {e}")
    
    # Check 8: 测试文件已删除
    checks_total += 1
    deleted_tests = [
        "backend/tests/test_yfinance_router_extra.py",
        "backend/tests/core/test_yfinance_router_dist02.py",
        "backend/tests/services/test_yfinance_service_dist04.py",
    ]
    all_deleted = all(not Path(f).exists() for f in deleted_tests)
    if all_deleted:
        print(f"✅ 8. 相关测试文件已删除 ({len(deleted_tests)} 个)")
        checks_passed += 1
    else:
        remaining = [f for f in deleted_tests if Path(f).exists()]
        print(f"❌ 8. 测试文件未完全删除: {remaining}")
    
    # Summary
    print("\n" + "=" * 60)
    if checks_passed == checks_total:
        print(f"🎉 全部通过! ({checks_passed}/{checks_total})")
        print("=" * 60)
        print("\n✅ P3 变更本地验证完成，可以安全部署到 VPS")
        return 0
    else:
        print(f"⚠️  部分失败 ({checks_passed}/{checks_total})")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

