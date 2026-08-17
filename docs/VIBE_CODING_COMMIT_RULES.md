# VIBE_CODING_COMMIT_RULES.md — 空壳（禁止加载）

> **不要读本文档正文。** Git / 原子提交铁律已迁入仓库根 [`AGENTS.md`](../AGENTS.md) §6。
> 跨 IDE 编码宪法是 [`AGENTS.md`](../AGENTS.md)。Cursor 适配器是 [`.cursor/rules/vibe-coding.mdc`](../.cursor/rules/vibe-coding.mdc)。

原 v1.0（2026-07-10，~400 行）是一次巨型 commit 的应急纠正文，示例过期，且与 L0 重复。独特条款已迁入 `AGENTS.md` §6：

- 一条 commit 一个目的；建议 <200 行，硬顶 500 行
- 禁止 SuperCommit（>15 文件或 >1000 行）
- 配置/CI 与业务代码分开提交
- `feat|fix|perf|docs|refactor|test(scope): 说明`；禁止 force-push `main`

生产路径禁止 mock → `AGENTS.md` §3。交互 rebase / force-push-with-lease **不要**从旧文照抄。

历史全文见 git：`git log -p -- docs/VIBE_CODING_COMMIT_RULES.md`。
