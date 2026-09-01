# 数据库迁移（Alembic）

## 现状：单链

2026-08-31 修复。此前存在 **3 个 `down_revision = None` 的独立头** + **1 处悬空父版本**
（`fe05b` 的 `down_revision` 写成了文件名 `strat03a_add_strategy_version_tables`，
而真实 revision id 是 `strat03a`），导致 `alembic upgrade head` 根本无法执行。

当前链（唯一链根 `strat03a` → 唯一链尾 `fin03a`）：

```
strat03a → pt01a → ai04rag → fe05b_frontend_logs → sent01 → fin03a
```

`backend/tests/test_alembic_chain.py` 会静态校验：单 root、单 head、无悬空父版本。
**新增迁移请挂到链尾**，不要再造独立头。

## 生产库如何上线

⚠️ 两个前提：

1. `backend/main.py` 启动时执行 `Base.metadata.create_all(bind=engine)`，**新表会自动建出来**，
   但 `create_all` 不会给已存在的表加列。
2. 本目录的迁移**只覆盖增量**（strategy / paper / frontend_logs / financials 建表，
   RAG 与 retail_heat 加列），**基础表结构仍由 create_all 负责**。
   所以空库跑完 `upgrade head` 后仍需启动一次应用才有完整表；
   `ai04rag` / `sent01` 在目标表不存在时按设计跳过，不报错。

按环境选择：

- **表已由 create_all 建好的库**（绝大多数现有环境）：先打基线戳，**不要直接 upgrade**，
  否则会撞 `table already exists`：

  ```bash
  DATABASE_URL=postgresql://... alembic stamp head
  ```

  之后的新迁移才会被正常执行：

  ```bash
  DATABASE_URL=postgresql://... alembic upgrade head
  ```

- **全新库**：直接 `alembic upgrade head`（无需 stamp）。
- **旧表缺列的库**（如 `sentiment_records` 早期建、模型后加字段）：直接 `upgrade head` 会补列。

回滚：`alembic downgrade -1`，全量回退 `alembic downgrade base`（每条都写了 `downgrade()`）。

## 已验证（2026-08-31，SQLite 实跑）

- 空库 `upgrade head`：6 步全通过，`alembic current` = `fin03a (head)`。
- 旧表缺列场景：`sentiment_records` 补出 `retail_heat_change_pct`/`retail_heat_total`，
  `webpage_knowledge_base` 补出 `category`/`embedding_model_version`。
- 往返：`downgrade base` → 再 `upgrade head` 可重复执行，无残留报错。

## 书写约定

- 加列一律用 **inspector 判列后再加**（`ai04rag` / `sent01` 的写法），禁止直接写
  PG 专有的 `ADD COLUMN IF NOT EXISTS` —— SQLite 下会语法错误，dev 与测试环境跑不了。
- `down_revision` 必须是 **revision id**，不是文件名。
- 幂等优先：迁移应可重复执行，部分失败重跑不炸。
- 新迁移挂链尾，`test_alembic_chain.py` 会拦住多头与断链。
