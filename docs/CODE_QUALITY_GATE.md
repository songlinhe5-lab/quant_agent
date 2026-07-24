# 代码质量门禁配置指南

## 📋 **预提交钩子 (Pre-commit Hook)**

本项目使用 git pre-commit hook 自动检查 Python 代码质量。

### 🔧 **安装步骤**

1. **Hook 文件已存在**: `/.git/hooks/pre-commit`
2. **确保可执行权限**:
```bash
chmod +x .git/hooks/pre-commit
```

3. **验证安装**:
```bash
ls -la .git/hooks/pre-commit
```

### ⚙️ **自动化检查内容**

每次 `git commit` 时自动执行:

#### **1. Import 管理** ✅
- **I001**: Import 排序规范
- **F401**: 移除未使用的导入
- 自动修复并重新 staging

#### **2. 代码格式化** ✅
- **W291**: 删除行尾空格
- **W293**: 删除空白行空格  
- 自动删除多余空格

#### **3. 整体格式化** ✅
- `ruff format`: PEP8 样式格式化
- 统一缩进、换行等

#### **4. 完整性检查** ⚠️
- 运行完整 linting 检查
- 发现无法自动修复的问题会提示
- 可选择继续或取消 commit

---

## 🎯 **工作流程示例**

```bash
# 1. 修改多个 Python 文件
vim backend/adapters/akshare/akshare_adapter.py

# 2. Stage 修改
git add backend/adapters/akshare/akshare_adapter.py

# 3. 尝试 commit
git commit -m "feat: add new adapter"

# ↓ 此时会自动触发以下检查 ↓

🔧 Running pre-commit code quality checks...
📋 Found 1 staged Python file(s):
backend/adapters/akshare/akshare_adapter.py

1️⃣ Checking imports and unused code...
   Fixed import sorting, removed unused imports

2️⃣ Removing trailing whitespace...
   Removed 5 lines with trailing whitespace

3️⃣ Formatting code...
   Reformatted 1 file

4️⃣ Running full linter check...
✅ All code quality checks passed!

# 4. 自动 stage 修复后的版本
# 5. Commit 完成！
```

---

## 🚨 **常见问题处理**

### Q: Hook 不执行？
```bash
# 确保有执行权限
chmod +x .git/hooks/pre-commit

# 验证 hook 内容
cat .git/hooks/pre-commit | head -10
```

### Q: 找不到 uv/ruff?
```bash
# 确保虚拟环境已激活
source .venv/bin/activate

# 或者手动安装依赖
uv sync
```

### Q: 想临时跳过 hook?
```bash
# 使用 --no-verify 参数（不推荐）
git commit --no-verify -m "skip hooks"
```

---

## 📊 **相关配置**

### Ruff 配置 (`pyproject.toml`)
```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]
ignore = []

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

### UV 工具链
```bash
# 安装所有开发依赖
uv sync

# 单独运行 ruff 检查
uv run ruff check backend/

# 单独运行格式化
uv run ruff format backend/
```

---

## 💡 **最佳实践**

1. **本地先自己检查**:
```bash
uv run ruff check backend/
uv run ruff format --check backend/
```

2. **Commit 前主动修复**:
```bash
uv run ruff check --fix backend/
uv run ruff format backend/
```

3. **依赖 Hook 自动处理**:
- Hook 会在 commit 时自动修复简单问题
- 复杂问题会提示，由开发者决定下一步

4. **CI/CD 二次检查**:
- GitHub Actions 会再次运行完整检查
- 确保服务器端也符合标准

---

## 🎯 **覆盖范围**

| 检查项 | Hook 自动修复 | CI/CD 检查 |
|:------|:------|:-------|
| Import 排序 (I001) | ✅ | ✅ |
| 未使用导入 (F401) | ✅ | ✅ |
| 空白行空格 (W291/W293) | ✅ | ✅ |
| 代码格式 (PEP8) | ✅ | ✅ |
| 类型注解 | ⚠️ 提示 | ✅ |
| Security issues | ⚠️ 提示 | ✅ |
| Complexity warnings | ⚠️ 提示 | ✅ |

---

## 📝 **维护说明**

- **Hook 路径**: `.git/hooks/pre-commit`
- **适用对象**: 仅本地生效 (不在仓库中)
- **团队共享**: 每个团队成员需独立安装
- **版本同步**: Hook 脚本不会随代码更新，需手动维护

---

**最后更新**: 2026-07-10  
**作者**: VARB-2026-0708-001 Virtual Architecture Board
