# Prompt 版本管理规范

> **原则**：所有系统级 Prompt 统一纳入版本控制，变更必须附带 Eval 结果。

## 目录结构

```
prompts/
├── README.md                    # 本文件：规范说明
├── system/                      # 系统级 Prompt（Agent 主脑人设）
│   └── AGENT_SYSTEM.md          # → 符号链接至根目录 AGENTS.md
├── tasks/                       # 任务级 Prompt（子模型 / 专用 LLM 调用）
│   ├── sentiment_analysis.md    # 新闻情感分析
│   ├── screener_translate.md    # 选股 NLP → DSL 翻译
│   └── title_generator.md      # 会话标题生成
└── templates/                   # Prompt 模板（含变量占位符）
    └── _template.md            # 新 Prompt 模板
```

## Prompt 文件头部规范

每个 Prompt 文件必须在头部包含以下元信息（YAML Front Matter）：

```yaml
---
id: prompt-sentiment-001
name: 新闻情感分析
target_model: gpt-4o-mini-2024-11-20
input_variables:
  - headline: 新闻标题（string）
  - summary: 新闻摘要（string，可选）
output_format: JSON {score: int, label: enum, reasoning: string, summary_zh: string}
last_tested: 2026-07-13
eval_score: TBD
changelog: |
  2026-07-13: 初始版本，从 sentiment_service.py 提取
---
```

## 变更流程

1. 修改 Prompt 文件
2. 运行对应的 Eval 测试用例（见 `backend/tests/test_*_eval.py`）
3. 在 PR 描述中附带 Eval 结果对比
4. 更新文件头部的 `last_tested` 和 `eval_score`

## 当前 Prompt 代码位置索引

| Prompt 名称 | 文件 | 代码位置 | 状态 |
|:---|:---|:---|:---|
| Agent 系统指令 | `AGENTS.md` | `backend/main.py:1214` 加载 | ✅ 已外部化 |
| 新闻情感分析 | `tasks/sentiment_analysis.md` | `backend/services/sentiment_service.py:14` | 📋 待迁移 |
| 选股 NLP→DSL | `tasks/screener_translate.md` | `backend/services/screener_service.py:1050` | 📋 待迁移 |
| 会话标题生成 | `tasks/title_generator.md` | `hermes_agent/agent.py:280` | 📋 待迁移 |
| JSON 结构化提取 | — | `backend/services/llm_service.py:76` | 🔧 通用工具，保留内联 |
