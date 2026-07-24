# 🔧 Vibe Coding Commit Granularity Rules (AI 编码提交粒度规范)

## 📋 **核心理念**

> **"Small, focused commits = easier review + better traceability + lower risk"**

每次 commit 应该:
- ✅ 聚焦单一功能或修复
- ✅ 代码变更 < 500 lines (建议 < 200 lines)
- ✅ 自洽的完整功能单元
- ✅ 独立的测试验证通过

---

## 🎯 **最小粒度原则 (Minimum Atomic Unit)**

### **1. 单功能 Single Feature Rule** ⭐⭐⭐⭐⭐

❌ **错误**: 一次性实现 Epic 3 的全部 6 个指标
```bash
# BAD: All at once (本次的实际做法)
git commit -m "feat(indicators): expand to 15 indicators with 6 advanced metrics"
```

✅ **正确**: 逐个指标分步提交
```bash
# GOOD: One indicator per commit
git commit -m "feat(indicators): add ADX/DMI trend strength indicators"
git commit -m "feat(indicators): add CCI momentum oscillator"
git commit -m "feat(indicators): add VWMA volume-weighted average"
git commit -m "feat(indicators): add ATR% volatility percentage"
git commit -m "feat(indicators): add Elder-Ray bull/bear power"
git commit -m "feat(indicators): add Keltner channels breakout system"
```

---

### **2. 单一职责 Single Responsibility Rule** ⭐⭐⭐⭐⭐

❌ **错误**: 同一个 commit 混合架构 + 功能 + 配置
```bash
# BAD: Multiple concerns mixed
git commit -m "feat(phase1-3): complete Clean Architecture + Technical Indicators v2.0"
# 实际包含了：
# - Router 层解耦
# - Adapters 实现  
# - Application service 层
# - 15 个技术指标
# - 文档编写
# - 测试用例
```

✅ **正确**: 按职责拆分
```bash
# Step 1: Router layer changes only
git commit -m "refactor(router): simplify market.py HTTP protocol handling [OPT-001]"

# Step 2: DataSourcePort interface definition
git commit -m "feat(adapters): implement DataSourcePort abstraction [OPT-001]"

# Step 3: Futu adapter implementation
git commit -m "feat(adapters): add FutuMarketDataClient adapter [OPT-001]"

# Step 4: YFinance adapter implementation
git commit -m "feat(adapters): add YFinanceMarketDataClient adapter [OPT-001]"

# Step 5: AKShare adapter implementation
git commit -m "feat(adapters): add AKShareBrokerageClient adapter [OPT-001]"

# Step 6: MarketDataService application layer
git commit -m "feat(app): implement MarketDataService orchestration [OPT-001]"

# Step 7: Phase 2 indicator engine (separate epic)
git commit -m "feat(indicators): implement TechnicalIndicatorsPro v1.1 with 9 core metrics"

# Step 8: Individual EPIC-3 indicators (see #1 above)
```

---

### **3. 配置与代码分离 Configuration & Code Separation Rule** ⭐⭐⭐⭐

❌ **错误**: CI/CD配置、前端配置、后端代码混在一起
```bash
# BAD: Mixed configuration and refactoring
git commit -m "chore: add CI/CD coverage gate + router refactoring [OPT-007]"
```

✅ **正确**: 分开提交
```bash
# Config change only
git commit -m "ci: raise coverage threshold to 80% per OPT-007 [OPT-007]"

# Frontend config change
git commit -m "test(frontend): add vitest coverage thresholds [OPT-007]"

# Refactoring only (after code review of configs)
git commit -m "refactor(router): clean up market.py formatting"
```

---

## 📏 **量化标准 (Quantitative Metrics)**

### **Commit Size Guidelines**

| 类型 | 最大 Files | 最大 Lines | 说明 |
|:------|:----------|:----------|:------|
| **Bug Fix** | 3 files | < 100 lines | 单一 bug 修复 |
| **Feature (small)** | 5 files | < 200 lines | 小型独立功能 |
| **Feature (medium)** | 10 files | < 500 lines | 中型功能模块 |
| **Refactoring** | 5 files | < 300 lines | 仅重构不改逻辑 |
| **Config/Docs** | 8 files | N/A | 配置/文档更新 |
| **❌ SuperCommit** | > 15 files | > 1000 lines | **禁止!** |

---

### **当变更超过阈值时，如何拆分？**

#### **Scenario A: 多个独立指标**
```
Before (本次做法):
├─ backend/utils/advanced_indicators.py (new, 255 lines)
├─ tests/utils/test_advanced_indicators.py (new, 398 lines)
└─ docs/EPIC-003_FINAL_REPORT.md (new, 390 lines)

After (推荐做法):
1st commit: ADX/DMI
├─ Add _calculate_adx() function (~50 lines in existing file)
├─ Update technical_indicators_pro.py to register ADX
└─ Write unit test for ADX

2nd commit: CCI
├─ Add _calculate_cci() function (~50 lines)
├─ Register CCI
└─ Write unit test for CCI

... repeat for each indicator ...
```

#### **Scenario B: 架构改造 + 新功能**
```
Before (本次做法):
├─ Clean Architecture adapters
├─ MarketDataService application layer
└─ Technical Indicators v2.0 all together

After (推荐做法):
Phase 1-Router Layer First (complete before touching anything else)
├─ Commit 1: DataSourcePort interface
├─ Commit 2: Futu adapter
├─ Commit 3: YFinance adapter
├─ Commit 4: AKShare adapter
└─ Commit 5: Router simplification

Phase 2-Indicator Engine Second (start fresh)
├─ Commit 6: MA/EMA/MACD basic implementation
├─ Commit 7: RSI/Bollinger/ATR implementation
└─ Continue with individual features

Never mix Phase 1 architecture with Phase 2 features!
```

---

## 🔄 **开发流程规范化 (Standardized Workflow)**

### **正确的开发顺序 (Recommended Order)**

```
Step 1: Planning & Design
   └─ Create feature branch: git checkout -b feat/indicator-ADX
   └─ Plan: What's the ONE thing this PR will change?

Step 2: Implement Core Logic (FIRST)
   ├── Modify ONLY the calculation function
   ├── Test locally: python scripts/task1_validate_indicators.py
   └─ Commit: "feat(indicators): implement ADX calculation logic"

Step 3: Add Tests (SECOND)  
   ├── Write unit tests for the new indicator
   ├── Ensure all tests pass
   └─ Commit: "test(ADVANCED): add ADX validation tests"

Step 4: Documentation (THIRD)
   ├── Update API docs if needed
   ├── Add usage examples
   └─ Commit: "docs(technical): document ADX indicator API"

Step 5: Integration (FOURTH)
   ├── Register indicator in TechnicalIndicatorsEngine
   ├── Update DEFAULT_INDICATORS list
   └─ Commit: "feat(engine): register ADX indicator in engine"

Step 6: Performance Verification (FIFTH)
   ├── Run performance benchmark
   ├── Verify < target latency
   └─ Commit: "perf(ADVANCED): validate ADX performance < 2ms"

Step 7: Final Cleanup
   ├── Check git status, ensure no leftover temp files
   ├── Run ruff format, fix any lint issues
   └─ Commit: "chore: apply ruff format to ADX implementation"

Final: Push & Create PR
   ├─ git push origin feat/indicator-ADX
   └─ gh pr create --title "feat(indicators): add ADX/DMI support" 
```

### **关键原则: Each Step = Separate Commit**

每完成一个步骤就 commit，不要等待"完整功能就绪"!

---

## 🚫 **绝对禁止的行为 (Anti-Patterns)**

### ❌ **Monolithic Commit Anti-Pattern**

```bash
# NEVER DO THIS:
git commit -am "feat: Complete implementation of Phase 1-3, EPIC 001-004 with all indicators, adapters, documentation, tests, CI/CD updates, and architectural changes"

# This is what you did (bad example):
a4dd455 chore: add CI/CD coverage gate + router refactoring [OPT-007]
90fe2c9 feat(phase1-3): complete Clean Architecture + Technical Indicators v2.0 [EPIC-001~004]
29d2605 feat(indicators): expand to 15 indicators with 6 advanced metrics [EPIC-003]

# Problems:
# 1. Commit #2 contains ~6000 lines across 22 files
# 2. Mixes architecture + features + tests + docs
# 3. Cannot be reviewed atomically
# 4. Hard to revert if something breaks
# 5. Loses context about WHY each change was made
```

---

### ❌ **"All-at-once" Implementation Anti-Pattern**

```
BAD workflow:
1. Write ALL 6 new indicators → 255 lines
2. Write ALL tests → 398 lines  
3. Write ALL docs → 3 docs
4. Run ALL validations
5. Commit everything at once

GOOD workflow:
1. Write ADX indicator → commit immediately
2. Write ADX tests → commit immediately
3. Write ADX docs → commit immediately
4. Validate ADX → commit result
5. Repeat for CCI, VWMA, etc.
```

---

## 📝 **Commit Message Template (Atomic Commits)**

```markdown
# Format: type(scope): description [Epic/Task ID]

Examples:
✓ feat(indicator): implement ADX calculation [EPIC-003]
✓ test(indicator): add ADX unit tests [EPIC-003]
✓ refactor(router): simplify market.py parsing [OPT-001]
✓ ci: update coverage threshold to 80% [OPT-007]
✓ docs(adv-ind): add CCI usage examples [EPIC-003]

# For each commit, include:
1️⃣ ONE sentence summary (50 chars max)
2️⃣ WHAT changed (file names + line counts)  
3️⃣ WHY this change (business reason)
4️⃣ Impact assessment (performance, breaking changes)

# NEVER include:
✗ Multiple unrelated features
✗ Architecture decisions not directly related
✗ Unfinished/refactoring work
✗ Temporary debugging code
```

---

## 🎯 **AI Agent Behavior Checklist**

### **Before Generating Code:**

```
□ Ask: "What is the SINGLE smallest thing we need to change?"
□ Confirm: "Can this be done in < 200 lines?"
□ Plan: "What's the minimal viable implementation?"
□ Strategy: "Should this be split into multiple commits?"
```

### **During Code Generation:**

```
□ Generate ONE function/class at a time
□ Stop after every logical completion point
□ Ask: "Ready to commit this, or continue?"
□ Never batch multiple changes together
```

### **Before Creating Commit:**

```
□ Review `git diff` carefully
□ Count lines: Should this be split further?
□ Verify single responsibility: Is there one clear purpose?
□ Check dependencies: Are there orphaned files?
□ Confirm: Would I understand this in 6 months?
```

### **If Commit Becomes Large:**

```
□ Option 1: Squash into smaller commits
   git reset --soft HEAD~n && git commit -m "first atomic commit" && git commit -m "second..."

□ Option 2: Use interactive rebase
   git rebase -i HEAD~n (pick/edit/squash)

□ Option 3: Cherrypick to new commits
   git cherry-pick <commit-hash>^1
```

---

## 🔄 **Correction Procedure (When You've Already Done Monolithic Commits)**

### **Example: Split the current large commits**

```bash
# Current bad state:
# 90fe2c9 feat(phase1-3): complete Clean Architecture + Technical Indicators v2.0

# Solution: Interactive rebase to split
git rebase -i 29d2605~1  # Start from parent of first bad commit

# Then edit todo file:
pick 90fe2c9 Original large commit

# Change to:
edit 90fe2c9 Original large commit

# Now reset and re-commit piece by piece:
git reset HEAD~1  # Keep changes, remove commit

# Commit small pieces:
git commit -m "feat(adapters): implement DataSourcePort interface"
git commit -m "feat(adapters): implement FutuMarketDataClient"
git commit -m "feat(adapters): implement YFinanceMarketDataClient"
git commit -m "feat(adapters): implement AKShareBrokerageClient"
git commit -m "feat(app): implement MarketDataService layer"
git commit -m "feat(router): simplify market.py HTTP handling"
git commit -m "feat(indicators): implement 9 core indicators v1.1"
git commit -m "feat(indicators): implement 6 advanced indicators"
git commit -m "docs: add EPIC-003 final report"
# etc.

# Then force push (if already pushed to remote)
git push --force-with-lease origin develop
```

---

## 💡 **Key Takeaways**

### **Golden Rules:**

1. **One Commit = One Purpose**
2. **Under 500 lines total**
3. **Self-contained functionality**  
4. **Testable and reversible**
5. **Clear commit message**

### **Mindset Shift:**

From: "Let me implement the whole Epic first, then commit"
To: "Let me make the SMALLEST possible change, commit it, then move on"

### **Benefits:**

✓ Faster reviews (reviewers actually read everything)
✓ Better traceability (can find when/why any change happened)
✓ Lower risk (easier to revert broken parts)
✓ Clearer history (each commit tells a story)
✓ Less merge conflicts (smaller diffs merge more cleanly)

---

## 🚨 **This Rule Supersedes Previous Guidance**

Any previous instructions that suggested "complete full implementation before committing" are NOW OVERRIDDEN.

**New Standard: Always aim for atomic commits, even during development.**

Version: v1.0 (2026-07-10)  
Emergency correction triggered by monolithic commit discovery.
