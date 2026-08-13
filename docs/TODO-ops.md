# 🚀 TODO — 部署运维/监控/文档（拆分自 TODO.md 2026-08-13）

### 部署与运维

- [x] **[OPS-01]** GitHub Actions CI/CD 流水线：质量门（lint + test + coverage ≥70%）→ 前端 Cloudflare Pages 部署 → 后端 Docker 构建推送 ghcr.io → SSH 触发 VPS 滚动更新
- [x] **[OPS-02]** Tailscale 零信任：US-MASTER + US-YF-A/B + CN-AKSHARE 入同一 Tailnet；跨节点仅走 Tailscale；数据端口不对公网；SSH 优先 `tailscale ssh`（对齐 docs/06 V9.0）
- [x] **[OPS-03]** Docker Compose 生产配置：resource limits、restart policy、healthcheck 全部配置到位
- [x] **[OPS-04]** Redis AOF 持久化 + 每日自动 RDB 备份到 Cloudflare R2
- [x] **[OPS-05]** 备份恢复演练脚本：实现 `docs/12` 灾难恢复流程，定期验证 R2 备份可恢复性（RTO < 2h 验收）


### 可观测性落地

- [x] **[OBS-01]** Grafana Dashboard 配置：行情延迟分位数、WS 连接数、Redis 内存、API QPS/错误率、客户端 APM 面板（对照 `docs/08`）
- [x] **[OBS-02]** 告警通道接入：后端通知服务已支持飞书 Webhook 推送（`FEISHU_WEBHOOK_URL` + `FEISHU_SECRET` 签名），落地 `docs/12` §4 告警阈值表
- [x] **[OBS-03]** 前后端性能监控落地：前端 Web Vitals 上报 + 后端 API 延迟分位数 Grafana 可视化 ✅ **2026-07-13**：`web-vitals` → `/client/heartbeat`；Prometheus `quant_client_web_vital_*`；Grafana API P50/P99 + APM/Vitals 面板；修复 P95 告警指标名为 `fastapi_request_duration_seconds`
- [x] **[OBS-04]** Grafana Alerting → 飞书 Webhook 集成：Contact Point 已配置 (`alerting.yml` feishu-alerts)，RL-11 新增 4 条限流告警规则已接入飞书推送；待补充：非限流类告警 (如 SVC 数据源 Down) 的 Contact Point 配置


### 文档

- [x] **[DOC-01]** `docs/subsystems/agent/architecture.md` 补充 Tool 开发模板（入参/出参/错误码规范） ✅ **2026-07-13**（§3.1 入参 JSON Schema 规范 + §3.2 出参统一响应协议 + §3.3 错误码枚举 + §3.4 Tool 骨架模板 + §3.5 测试模板）
- [x] **[DOC-02]** 各子系统性能基准数据补充（当前 `docs/09. 性能测试规范.md` 中标注 TBD 的部分） ✅ **2026-07-13**（§1.1 实测基准数据：技术指标 / 告警评估 / 指标评估器 / K线序列化 10 项基准采集，全部达标）
- [x] **[DOC-03]** 废弃 `docs/backend.md` 和 `docs/frontend.md`（已标注 Deprecated），后续清理 ✅ **2026-07-13**（文件已删除；`docs/07` API 速查引用更正为 `docs/10` + `openapi.json`；`ARCHITECTURE_REVIEW.md` 标记完成）

### 架构审计补漏（2026-07-13 新增，来源 `ARCHITECTURE_REVIEW.md`）

> 架构审计报告中标注的改进项，经筛选后纳入任务跟踪。已覆盖的项（SEC/ALERT/MIG/OBS 等）不重复录入。

#### AI 工程规范（ARCHITECTURE_REVIEW §四）

- [x] ~~**[AI-01]** Prompt 版本管理：建立 `prompts/` 目录统一收纳系统级 Prompt（工具 Prompt / 策略生成 / 报告生成），纳入 Git 版本控制；每个 Prompt 头部注明使用场景/目标模型/输入变量/预期输出；变更需附 Eval 结果~~ ✅ **2026-07-13**（`prompts/` 目录结构 + README + 3 个 task prompt + template + system reference）
- [x] ~~**[AI-02]** LLM 模型版本钉定 + 多模型路由：配置文件锁定 LLM 模型版本（如 `gpt-4o-2024-11-20`）防静默升级；轻量任务→小模型 / 深度研报→旗舰模型分级路由；OpenAI 不可用时自动降级至本地 Ollama~~ ✅ **2026-07-13**（`LLMRouter` + `ModelTier` 三级路由 + Ollama 降级 + 版本钉定 + 12 tests）
- [x] ~~**[AI-03]** Agent Eval 评估框架：建立 Golden Dataset（≥50 用例，覆盖正常/边界/故障）；定义幻觉检测指标（数字准确率 / 引用溯源率 / DSL 合规率）；接入 GitHub Actions 每周自动运行~~ ✅ **2026-07-13**（`EvalMetrics` + 55 例 Golden Dataset + `EvalRunner` + `eval.yml` CI + 26 tests）
- [x] ~~**[AI-04]** RAG 知识库治理：定义各类文档 TTL（财报 90d / 新闻 7d / 宏观 30d）自动触发清理；Embedding 模型版本记录 + 升级时全量重建；检索质量监控（相似度低于阈值告警）~~ ✅ **2026-07-13**（分类 TTL + embedding 版本管理 + 检索质量监控 + Alembic 迁移 + 11 tests）

#### 产品与部署（ARCHITECTURE_REVIEW §二/§六/§七）

- [x] ~~**[ARCH-01]** Futu OpenD 部署前提文档：补充宿主机要求（禁 ARM，必须 x86）+ 跨地域部署限制（港股实盘必须低延迟香港节点）~~ ✅ **2026-07-13**（`docs/12` §八：硬件约束 + 地域限制 + 版本管理）
- [x] ~~**[ARCH-02]** DuckDB 数据湖分区策略：定义 Parquet 文件分区规则（按标的+日期分区），避免单文件过大影响查询性能~~ ✅ **2026-07-13**（`docs/12` §九：三级分区规则 + 迁移策略 + 查询优化）
- [x] ~~**[ARCH-03]** Futu OpenD 断连恢复 SOP：定义"暂停接单 → 断线检测 → 重连 → 状态对账"完整流程，在途订单处理方案文档化~~ ✅ **2026-07-13**（`docs/12` §十：影响矩阵 + 自动恢复 + 在途对账 SOP + 人工介入 + 演练计划）


### 另类数据

- [ ] **[ALT-01]** Reddit WallStreetBets + X (Twitter) 散户情绪流监控
- [ ] **[ALT-02]** 财报电话会议（Earnings Call）音频情感分析（声纹情绪 + 语气波动）
- [ ] **[ALT-03]** 链上大资金追踪（针对加密资产，交易所净流入/流出预警）

---

