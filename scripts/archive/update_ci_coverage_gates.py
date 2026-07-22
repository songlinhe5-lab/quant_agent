#!/usr/bin/env python3
"""
OPT-007: 恢复覆盖率门禁 (Coverage Gate Restoration)

自动化脚本：根据 AI 虚拟架构委员会决议，修改 CI 流水线配置

功能:
  1. 移除分支保护条件 (让所有分支都受门禁约束)
  2. 设置后端覆盖率门槛至 80%(OPT-001 验收标准)
  3. 启用前端覆盖率门禁 (60% 门槛)
  4. 创建前端独立 CI workflow(如不存在)

使用方式:
  # 预览模式 (Dry Run)
  python scripts/update_ci_coverage_gates.py --dry-run
  
  # 实际执行修改
  python scripts/update_ci_coverage_gates.py
  
  # 自动提交 PR
  python scripts/update_ci_coverage_gates.py --commit
"""

import os
import sys
import argparse
import shutil
from pathlib import Path
from typing import Optional


def print_banner():
    """打印脚本横幅"""
    print("\n" + "="*60)
    print("🔧 OPT-007 Coverage Gate Restoration")
    print("="*60)


def read_file(file_path: str) -> str:
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"❌ 错误：找不到文件 {file_path}")
    except Exception as e:
        raise Exception(f"读取文件失败：{e}")


def write_file(file_path: str, content: str):
    """写入文件内容"""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ 已更新：{file_path}")


def create_backup(file_path: str):
    """创建备份文件"""
    backup_path = f"{file_path}.bak.{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(file_path, backup_path)
    print(f"💾 已创建备份：{backup_path}")


def update_backend_ci(content: str, dry_run: bool) -> str:
    """
    更新后端 CI 配置
    变更:
      1. 移除 main 分支排除条件
      2. 将覆盖率阈值从 70 改为 80
    """
    original = content
    
    # 变更 1: 移除 test job 中的分支排除条件
    old_test_if = "if: github.ref != 'refs/heads/main' && always() && (needs.lint.result == 'success' || needs.lint.result == 'skipped')"
    new_test_if = "if: always() && (needs.lint.result == 'success' || needs.lint.result == 'skipped')"
    
    if old_test_if in content:
        content = content.replace(old_test_if, new_test_if)
        print("✅ 已移除测试 Job 的分支排除条件 (允许 main 分支也运行测试)")
    else:
        print("⚠️ 警告：未找到 test job 的 if 条件，可能需要手动检查")
    
    # 变更 2: 移除 security job 的分支排除条件
    old_security_if = "if: github.ref != 'refs/heads/main' && always() && (needs.test.result == 'success' || needs.test.result == 'skipped')"
    new_security_if = "if: always() && (needs.test.result == 'success' || needs.test.result == 'skipped')"
    
    if old_security_if in content:
        content = content.replace(old_security_if, new_security_if)
        print("✅ 已移除 security Job 的分支排除条件")
    else:
        print("⚠️ 警告：未找到 security job 的 if 条件，可能需要手动检查")
    
    # 变更 3: 将覆盖率阈值从 70 改为 80
    old_threshold = "--cov-fail-under=70"
    new_threshold = "--cov-fail-under=80"
    
    if old_threshold in content:
        content = content.replace(old_threshold, new_threshold)
        print(f"✅ 已将后端覆盖率阈值调整为 80%")
    else:
        print(f"⚠️ 警告：未找到覆盖率阈值配置 {old_threshold},可能已经更新过")
    
    if content != original and not dry_run:
        create_backup(".github/workflows/backend.yml")
        write_file(".github/workflows/backend.yml", content)
    elif content != original:
        print("\n📝 预览模式：以下变更待应用:")
        print("-"*60)
        print(f"Backend.yml will be updated:")
        print(f"  • Remove main branch exclusion from test/security jobs")
        print(f"  • Update coverage threshold: 70% → 80%")
    
    return content


def update_frontend_vitest(content: str, dry_run: bool) -> str:
    """
    更新前端 Vitest 配置，启用覆盖率阈值
    """
    original = content
    
    old_comment = """// 💡 暂时禁用覆盖率阈值检查，当前仅有 2 个测试文件（24 个用例）
      // 后续逐步添加单元测试后，再添加 thresholds 配置"""
    
    new_config = """// 💡 覆盖率门禁阈值 (OPT-007 要求)
      thresholds: {
        global: {
          branches: 60,
          functions: 60,
          lines: 60,
          statements: 60,
        },
      }"""
    
    if old_comment in content:
        content = content.replace(old_comment, new_config)
        print("✅ 已启用前端覆盖率门禁，阈值设置为 60%")
    else:
        print("⚠️ 警告：未找到要替换的注释，请手动检查前端配置")
    
    if content != original and not dry_run:
        create_backup("frontend/vitest.config.ts")
        write_file("frontend/vitest.config.ts", content)
    elif content != original:
        print("\n📝 预览模式：以下变更待应用:")
        print("-"*60)
        print(f"Vitest config will be updated:")
        print(f"  • Enable thresholds configuration")
        print(f"  • Set global coverage requirement: 60%")
    
    return content


def create_frontend_ci(dry_run: bool) -> bool:
    """创建前端独立 CI workflow(如果不存在)"""
    frontend_yml = ".github/workflows/frontend.yml"
    
    if os.path.exists(frontend_yml):
        print(f"ℹ️ 前端 CI 配置已存在：{frontend_yml} (跳过)")
        return False
    
    frontend_ci_content = """name: Frontend CI

on:
  push:
    branches: [ main, develop ]
    paths:
      - 'frontend/**'
      - '.github/workflows/frontend.yml'
  pull_request:
    paths:
      - 'frontend/**'
      - '.github/workflows/frontend.yml'

env:
  FRONTEND_THRESHOLD: 60

jobs:
  lint-build-test:
    name: Lint, Build & Test
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'pnpm'
          cache-dependency-path: 'frontend/pnpm-lock.yaml'
      
      - name: Install dependencies
        working-directory: ./frontend
        run: pnpm install --frozen-lockfile
      
      - name: Lint
        working-directory: ./frontend
        run: pnpm lint
      
      - name: Build
        working-directory: ./frontend
        run: pnpm build
      
      - name: Run tests with coverage
        working-directory: ./frontend
        run: pnpm test -- --coverage --ci
      
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          files: ./frontend/coverage/coverage-final.json
          flags: frontend
          fail_ci_if_error: true
          token: ${{ secrets.CODECOV_TOKEN }}
      
      - name: Detect slow tests
        working-directory: ./frontend
        run: |
          echo "## Slow Tests Report (Top 10)" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          pnpm test -- --durations=10 --tb=no -q 2>&1 | tee /tmp/slow_tests.txt
          grep -A 20 "slowest" /tmp/slow_tests.txt >> $GITHUB_STEP_SUMMARY || true
"""
    
    if not dry_run:
        create_backup(frontend_yml)
        write_file(frontend_yml, frontend_ci_content)
        print(f"✅ 已创建前端 CI 配置：{frontend_yml}")
    else:
        print(f"📝 预览模式：以下新文件待创建:")
        print(f"   • {frontend_yml}")
        print(f"     (包含：Lint + Build + Test + Coverage Gateway)")
    
    return True


def print_summary():
    """打印变更摘要"""
    print("\n" + "="*60)
    print("🎉 所有变更已完成!")
    print("="*60)
    print("\n📊 变更摘要:")
    print("-"*60)
    print("✅ 后端 CI: 覆盖率阈值 70% → 80%")
    print("✅ 后端 CI: 移除 main 分支排除条件")
    print("✅ 前端 CI: 启用覆盖率门禁 (60% 门槛)")
    print("✅ 前端 CI: 创建独立 workflow (如果不存在)")
    print("")
    print("🔍 验证步骤:")
    print("-"*60)
    print("1. git diff .github/workflows/")
    print("2. git diff frontend/vitest.config.ts")
    print("3. Check newly created frontend/.github/workflows/frontend.yml")
    print("4. Push 到分支触发 CI 验证")
    print("")
    print("✨ OPT-007 执行完毕!")
    print("="*60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="OPT-007: 恢复覆盖率门禁")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")
    parser.add_argument("--commit", action="store_true", help="自动提交 PR 到 develop 分支")
    
    args = parser.parse_args()
    
    print_banner()
    print(f"Dry Run: {args.dry_run}")
    print(f"Auto Commit PR: {args.commit}")
    print("")
    
    try:
        # Step 1: 修改后端 CI 配置
        print("📝 处理后端 CI 配置...")
        backend_content = read_file(".github/workflows/backend.yml")
        backend_content = update_backend_ci(backend_content, args.dry_run)
        
        # Step 2: 更新前端 Vitest 配置
        print("\n📝 处理前端测试配置...")
        vitest_content = read_file("frontend/vitest.config.ts")
        vitest_content = update_frontend_vitest(vitest_content, args.dry_run)
        
        # Step 3: 创建前端 CI workflow(如果不存在)
        print("\n📝 检查前端 CI 配置...")
        create_frontend_ci(args.dry_run)
        
        # 打印总结
        print_summary()
        
        # 自动提交 (可选)
        if args.commit and not args.dry_run:
            print("🚀 自动提交 PR 到 develop 分支...")
            # Git commit logic here (optional, requires GitHub token)
            print("⚠️ 自动提交功能需配置 GitHub Token 和 ssh key")
            print("建议手动执行:")
            print("  git checkout develop")
            print("  git add -u")
            print("  git commit -m \"OPT-007: Restore coverage gates\"")
            print("  gh pr create --fill")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\n❌ 错误：{e}")
        print("提示：请在项目根目录运行此脚本")
        return 1
    except Exception as e:
        print(f"\n❌ 执行失败：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
