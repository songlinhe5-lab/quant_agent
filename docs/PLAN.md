# 📋 Quant Agent 开发计划

> **文档定位**: 记录每个开发会话的具体执行计划与进度追踪  
> **关联文档**: [TODO.md](./TODO.md) - 全工程任务追踪 | [MASTER_REVIEW.md](./MASTER_REVIEW.md) - 架构决策

---

## 🎯 当前阶段目标

**阶段主题**: 前后端基础设施并行推进 + 可观测性落地

**时间窗口**: 2026-06-28 ~

---

## 📅 会话计划

### 会话 1: 后端启动验证与问题修复 (2026-06-28) ✅

**目标**: 启动后端服务，验证所有核心接口能力

**执行任务**:
- [x] 修复 `from core.` 错误导入路径
- [x] 启动后端服务 (uvicorn)
- [x] 验证健康检查 `/api/v1/health`
- [x] 验证认证接口 `/api/v1/auth/login`
- [x] 验证行情接口 `/api/v1/market/quote`
- [x] 验证宏观数据接口
- [x] 更新 TODO.md 标记已完成任务 + 新增任务

**验收结果**:
- ✅ 后端启动成功，PID 33985
- ✅ PostgreSQL / Redis / Futu OpenD 全部连接正常
- ✅ 50+ 路由已注册，核心接口响应正常
- ✅ 实时行情数据正常（腾讯 411.8 HKD）

---

### 会话 2: 前端基础设施 (FE-01~05) 🔄

**目标**: 搭建前端核心架构骨架

**执行任务**:
- [ ] **FE-01**: 全局 `TradingDashboard` Keep-Alive 模块切换架构
  - 替换 React Router 全页路由为 Tab 式模块切换
  - 防止行情订阅因页面切换断开
  - 实现模块状态持久化
  
- [ ] **FE-02**: 底部 `StatusBar` 组件
  - WS 连接状态灯（绿/黄/红）
  - 当前延迟 ms 显示
  - 账户净值 / 当日盈亏
  
- [ ] **FE-03**: WebSocket 断线 5 步处理流程
  - 断线检测 → 状态灯变红 → 图表 STALE overlay → 指数退避重连 → 重连成功后重订阅
  
- [ ] **FE-04**: 三级 Error Boundary
  - Module 级 / Panel 级 / Chart 级错误隔离
  - 防止单组件崩溃影响全局
  
- [ ] **FE-05**: `frontend/src/lib/logger.ts` 实现
  - level 过滤（debug/info/warn/error）
  - 生产环境上报 `/api/v1/logs/frontend`

**依赖检查**:
- [x] MIG-01~10 前端迁移已完成
- [x] SEC-07~09 前端安全已完成
- [x] BE-14 Pydantic 领域模型已定义

---

### 会话 3: 前端基础设施续 (FE-16~20)

**目标**: 前端数据层封装

**执行任务**:
- [ ] **FE-16**: API client 三通道封装（REST / WS / SSE）
  - 统一 baseURL、错误码处理
  - 请求拦截器自动用 Refresh Token 续期 Access Token
  
- [ ] **FE-17**: WebSocket 客户端封装
  - 连接生命周期管理
  - 自动重连（指数退避）
  - 订阅去重
  - 页面 `visibilitychange` 隐藏时暂停订阅
  
- [ ] **FE-18**: 前端 TypeScript 类型定义
  - 落地 `src/types/domain.ts`
  - 与 `docs/11` 领域对象严格对齐
  
- [ ] **FE-19**: IndexedDB 历史 K线本地缓存
  - 减少重复 HTTP 拉取
  - 离线可读最近行情
  
- [ ] **FE-20**: Web Worker 指标计算下放
  - MACD / RSI / 布林带等重度计算移出主线程

---

### 会话 4: 后端可观测性 (OBS-01/02) 🔄

**目标**: Grafana 仪表板 + 告警通道落地

**执行任务**:
- [x] **OBS-01**: Grafana Dashboard 配置
  - 行情延迟分位数面板
  - WS 连接数面板
  - Redis 内存 / API QPS / 错误率
  - 客户端 APM 面板
  
- [x] **OBS-02**: 告警通道接入
  - Grafana Alerting → Bark / 微信 webhook
  - 落地 `docs/12` §4 告警阈值表

**验收标准**:
- [ ] Grafana 可访问 http://localhost:3000
- [ ] 仪表板数据正常展示
- [ ] 告警规则触发后能收到通知

---

### 会话 5: 前端体验优化 (FE-25~30)

**目标**: 视觉主题统一 + 性能监控

**执行任务**:
- [ ] **FE-25**: 视觉主题统一
  - 深色模式为主
  - 参考 Linear/Vercel 风格
  - 统一配色变量与组件风格
  
- [ ] **FE-26**: 视觉稿参考整理
  - 收集 Linear / Vercel / Robinhood 视觉特征
  - 形成设计规范文档
  
- [ ] **FE-27**: 前端性能监控
  - 接入 Web Vitals (LCP / FID / CLS)
  - 开发阶段实时显示
  - 生产环境上报
  
- [ ] **FE-28**: 交互细节优化
  - 统一 Loading 状态
  - Toast 通知
  - 过渡动画时长与缓动曲线
  
- [ ] **FE-29**: 响应式布局完善
  - 确保 1280px / 1440px / 1920px 三档分辨率下布局合理
  
- [ ] **FE-30**: 前端错误边界完善
  - 全局 ErrorBoundary + 模块级降级
  - 捕获渲染崩溃并上报日志

---

## 📊 进度追踪

| 会话 | 主题 | 状态 | 完成度 |
|------|------|------|--------|
| 会话 1 | 后端启动验证 | ✅ 完成 | 100% |
| 会话 2 | 前端基础设施 FE-01~05 | 🔄 进行中 | 0% |
| 会话 3 | 前端数据层 FE-16~20 | ⏳ 待开始 | 0% |
| 会话 4 | 后端可观测性 | ✅ 配置完成 | 100% |
| 会话 5 | 前端体验优化 | ⏳ 待开始 | 0% |

---

## 🔗 关键链接

- [TODO.md](./TODO.md) - 全工程任务追踪
- [MASTER_REVIEW.md](./MASTER_REVIEW.md) - 架构决策记录
- [docs/08 日志与可观测性规范](./08.%20日志与可观测性规范.md)
- [docs/12 运维手册与应急预案](./12.%20运维手册与应急预案.md)

---

## 📝 会话笔记

### 2026-06-28 后端启动验证

**遇到的问题**:
1. `from core.` 导入路径错误 → 修复为 `from backend.core.`
2. `from services.` 导入路径错误 → 修复为 `from backend.services.`

**验证通过的接口**:
- `/api/v1/health` - 健康检查
- `/api/v1/auth/login` - 认证
- `/api/v1/market/quote` - 实时行情
- `/api/v1/market/fundamental/{ticker}` - 基本面
- `/api/v1/market/news` - 市场新闻
- `/api/v1/macro/sentiment-history` - 宏观情绪
- `/api/v1/macro/calendar` - 宏观日历
- `/api/v1/market/futu/status` - Futu 状态
- `/api/v1/market/health/services` - 服务健康
- `/api/v1/client/heartbeat/stats` - 客户端心跳统计

**后端运行状态**:
- PID: 33985
- 端口: 8000
- PostgreSQL: ✅ connected
- Redis: ✅ connected
- Futu OpenD: ✅ CONNECTED
