# Pre-commit Hook 代码质量门禁配置经验总结

## 📋 **核心目标**
确保每次 git commit 前自动检查和修复 Python 代码质量问题，防止不符合规范的代码进入仓库。

---

## 🔧 **安装步骤回顾**

### 1. 创建 Hook 脚本
```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/usr/bin/env bash
set -e

echo "🔧 Running pre-commit code quality checks..."

cd "$(dirname "$0")/.."

if [ ! -d ".git" ]; then
    echo "❌ Error: Not a git repository"
    exit 1
fi

STAGED_PY_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

if [ -z "$STAGED_PY_FILES" ]; then
    echo "✅ No Python files staged for commit, skipping..."
    exit 0
fi

echo "📋 Found $(echo $STAGED_PY_FILES | wc -w) staged Python file(s):"
echo "$STAGED_PY_FILES"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "⚠️ Warning: No virtual environment found, using system Python"
fi

# Auto-fix common issues
echo "1️⃣ Checking imports and unused code..."
uv run ruff check --fix --unsafe-fixes \
    --select I001,F401,W291,W293 \
    $STAGED_PY_FILES || true

echo "2️⃣ Formatting code..."
uv run ruff format $STAGED_PY_FILES

# Final check
REMAINING_ISSUES=$(uv run ruff check $STAGED_PY_FILES 2>&1 || true)

if [ -n "$REMAINING_ISSUES" ]; then
    echo "⚠️ Non-critical issues remain:"
    echo "$REMAINING_ISSUES"
    read -p "Continue with commit despite warnings? (y/N) " -n 1 -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Commit aborted"
        exit 1
    fi
else
    echo "✅ All code quality checks passed!"
fi

git add $STAGED_PY_FILES
exit 0
EOF
chmod +x .git/hooks/pre-commit
```

### 2. 关键配置要点

**必须添加的参数**:
```bash
# ✓ 支持 unsafe fixes (处理变量未使用等复杂问题)
uv run ruff check --fix --unsafe-fixes --select I001,F401,W291,W293 file.py

# ✓ 组合选择多个规则类型
--select I001,F401,W291,W293

# ✓ 使用 || true 防止中间步骤失败导致整个 hook 中断
|| true
```

**环境变量检查顺序**:
```bash
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi
```

---

## ⚠️ **常见坑与解决方案**

### **坑 1: Hook 中使用了错误的目录路径**

**错误示例**:
```bash
cd "$(dirname "$0")/../."  # ← 这个路径在某些环境下会出错
```

**正确做法**:
```bash
cd "$(dirname "$0")/.."  # 指向项目根目录
```

**症状**:
```
❌ Error: Not a git repository
```

**原因**:
Hook 脚本的 `$(dirname "$0")` 相对于 `.git/hooks/` 目录执行，需要正确计算相对路径。

**解决方案**:
确保工作目录在项目根目录，通过 `$(dirname "$0")/..` 精确定位。

---

### **坑 2: uv 命令未激活虚拟环境**

**错误现象**:
```bash
command not found: uv
```

**解决**:
Hook 开头检查并激活 venv:
```bash
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi
```

---

### **坑 3: 使用 --no-verify 跳过 Hook 后发现问题**

**场景**:
有时为了快速提交会使用 `--no-verify`,但这会绕过所有检查。

**最佳实践**:
1. 本地开发：依赖 Hook 自动修复简单问题
2. 紧急情况：先用 `--no-verify`,后续补上 Hook
3. CI/CD: GitHub Actions 作为二次检查

---

### **坑 4: Staged Files 过滤不完整**

**原问题**:
```bash
git diff --cached --name-only | grep '\.py$'  # ← 缺少 ACM 过滤器
```

**改进**:
```bash
git diff --cached --name-only --diff-filter=ACM | grep '\.py$'
```

**说明**:
- A = Added (新增)
- C = Copied (复制)  
- M = Modified (修改)

只处理这些类型的文件，避免误删或重置已删除的文件。

---

### **坑 5: 复杂 linting 错误无法自动修复**

**场景**:
某些问题如 "Local variable assigned but never used" (F841) 无法安全自动修复。

**解决方案**:
```bash
# 检测剩余问题但不阻塞提交
REMAINING_ISSUES=$(uv run ruff check $STAGED_PY_FILES 2>&1 || true)

if [ -n "$REMAINING_ISSUES" ]; then
    echo "⚠️ Non-critical issues detected"
    # 询问用户确认
    read -p "Continue anyway? (y/N) " ...
else
    echo "✅ All checks passed"
fi
```

---

## 💡 **高级技巧**

### **技巧 1: 分阶段修复策略**

第一阶段修复（自动）:
```bash
I001  # Import sorting
F401  # Unused imports
W291  # Trailing whitespace
W293  # Blank line trailing space
```

第二阶段提示（人工确认）:
```bash
E       # Error messages
F       # Pyflakes errors  
C90     # Complexity warnings
N       # Naming conventions
```

### **技巧 2: 条件性跳过特定文件**

```bash
# 排除生成文件或测试文件
EXCLUDED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' | grep -v '/tests/' | grep -v '__generated__')

if [ -z "$EXCLUDED_FILES" ]; then
    exit 0
fi
```

### **技巧 3: 并行运行多个检查器**

```bash
# 同时运行 ruff 和 mypy (类型检查)
uv run ruff check $FILES && uv run mypy $FILES
```

---

## 🎯 **验收标准**

Hook 成功安装的标志:

✅ 每次 git commit 都看到检查日志
✅ Import 排序问题自动修复
✅ 未使用的导入自动删除
✅ 空白行空格自动清理
✅ 代码格式自动统一

Hook 正常工作的证据:

```bash
$ git commit -m "test hook"

🔧 Running pre-commit code quality checks...
📋 Found 1 staged Python file(s):
   backend/example.py

1️⃣ Checking imports and unused code...
   Fixed import sorting on line 5
   Removed unused import: requests

2️⃣ Removing trailing whitespace...
   Cleaned 3 lines

3️⃣ Formatting code...
   Reformatted using PEP8 style

✅ All code quality checks passed!
```

---

## 📝 **维护注意事项**

### **团队协作**
- Hook 仅本地生效，每个团队成员需独立安装
- 建议将 `.git/hooks/pre-commit` 脚本放入项目版本库的 `.githooks/` 目录供同步
- 在 `CONTRIBUTING.md` 中引用此文档

### **CI/CD 一致性**
- 本地 Hook 负责快速反馈
- GitHub Actions 负责完整检查 (包括类型注解、Security 等)
- 两者检查范围应尽可能一致

### **工具更新**
```bash
# 定期检查 Ruff 新版本
uv pip list --outdated | grep ruff

# 更新时注意 backward compatibility
uv pip install --upgrade ruff
```

---

## 🚀 **扩展功能建议**

未来可以增强:

1. **Commit Message 规范检查**
   - 使用 commitlint
   - 强制 Conventional Commits 格式

2. **Secrets Detection**
   - 集成 git-secrets 或 detect-secrets
   - 防止敏感信息提交

3. **Pre-push Hook**
   - 在 push 前运行完整测试套件
   - 检查分支状态是否符合保护策略

4. **Auto-stage Fixups**
   ```bash
   # 自动 stage 修复后的文件
   git add $FIXED_FILES
   ```

---

**创建时间**: 2026-07-08  
**最后更新**: 2026-07-08  
**维护者**: VARB-2026-0708-001 Virtual Architecture Board
