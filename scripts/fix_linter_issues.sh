#!/bin/bash
# Quick Fix Script for Ruff Linter Issues

echo "🔧 Running automatic fixes..."

cd /Users/stephenhe/Development/workspace/quant_agent

# 1. Auto-fix all fixable issues
echo "1️⃣ Auto-fixing fixable issues..."
source .venv/bin/activate
uv run ruff check --fix backend/

# 2. Format all code
echo "2️⃣ Formatting code..."
uv run ruff format backend/

# 3. Check remaining issues
echo "3️⃣ Checking remaining issues..."
uv run ruff check backend/

echo ""
echo "✅ Fix complete! Please review any non-auto-fixed warnings."
