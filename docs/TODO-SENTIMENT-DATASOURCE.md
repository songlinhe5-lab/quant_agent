# TODO — 散户情绪数据源接入调研与计划

> 创建时间：2026-08-13
> 状态：调研已完成，**代码未开始**（后期开动）
> 目标：为 quant_agent 补齐「散户情绪面」维度，与现有机构情绪指标（VIX / P-C Ratio / Credit Spread）形成双层视图。

---

## 一、背景与动机

系统现有舆情/情绪能力盘点：

- **机构情绪**：`get_macro_sentiment_history`（P/C Ratio、VIX、Credit Spread）已内置。
- **新闻舆情**：`get_company_news` / `get_macro_news` / `search_worker`（非结构化文本检索）。
- **缺口**：缺少「散户（Retail）讨论热度与多空情绪」这一层，对标富途「情绪温度计」功能。

> 触发来源：评估富途 OpenD Skills / 情绪温度计 Skill 时发现，富途社区情绪数据**无公开 API**（仅能通过其 Skill 内部逻辑获取），故需另找程序化数据源。

---

## 二、数据源验证结论（实测，勿重复踩坑）

### 2.1 Finnhub Social Sentiment — ❌ 否决

- 端点：`https://finnhub.io/api/v1/stock/social-sentiment?symbol=AAPL&token=<key>`
- **实测（2026-08-13）**：返回 `{"error":"You don't have access to this resource."}`
- **根因**：当前 `FINNHUB_API_KEY` 为免费档，Social Sentiment 端点需付费解锁。
- **结论**：为单个情绪端点升付费档 ROI 过低，**放弃**。
- 教训固化：**先验证 Key 权限再写代码**，免费档往往不包含社交情绪端点。

### 2.2 StockGeist.ai — ❌ 否决（API 后端不稳定）

- 官网 `www.stockgeist.ai` 存活（HTTP 200）。
- **实测（2026-08-13）**：
  - API 文档端点 `api.stockgeist.ai/v2/docs` → **HTTP 502**（服务不可用）。
  - 无 Key 试探 `message_metrics` → 无正常响应。
- 附加风险信号：官方 Python client（`stockgeist/stockgeist-client-python`）最新示例停在 2021 年、仅 4 Star、42 commit。
- **结论**：API 后端 502，不稳定，**不能进生产数据源链路**（本架构无本地降级，接天生不稳的源等于埋雷）。

### 2.3 富途社区（牛牛圈）情绪 — ❌ 无公开 API

- 富途 OpenAPI 仅提供**行情 + 交易**两大类，无社区/舆情/情绪接口。
- 「情绪温度计」Skill 数据源为富途社区帖子，仅能通过装 Skill 用自然语言调，**无 REST/SDK**。
- A股/港股散户情绪（雪球、东方财富股吧）只能爬虫，反爬严重，不适合常驻数据源。
- **结论**：A股/港股散户情绪**本期放弃**。

### 2.4 Utradea Social Sentiment — ⚠️ 维护停滞

- 调研文（2026-06）提示 RapidAPI 列表最后更新 2024-07，存在维护停滞迹象。
- 未实测，**不推荐**。

### 2.5 ApeWisdom — ✅ 可用（仅热度榜，无情绪分数）

- 端点：`https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}`
- **实测（2026-08-13）**：免费无 Key、无认证，直接调通，返回 1009 只股票热度榜。
- 字段：`rank` / `ticker` / `name` / `mentions`（提及数）/ `upvotes`（点赞）/ `rank_24h_ago` / `mentions_24h_ago`。
- filter：`all-stocks` / `all-crypto` / `all`。
- **关键边界**：**只有热度/排名，没有情绪分数（sentiment score）**。它是「散户注意力热度榜」，不是「多空情绪」。

---

## 三、核心结论

1. **「多空情绪」在免费/低成本数据源中暂无可靠解**：Finnhub 403、StockGeist 502、富途无 API、Utradea 停滞。若要真正的多空情绪，只能上机构级付费源（Social Market Analytics / RavenPack，$299+/月），属另一决策，不在本期。
2. **「散户热度/注意力」可立即落地**：ApeWisdom 免费、无 Key、已实测可用。
3. **热度 ≠ 情绪**：必须作为两个独立指标分别定义、分别入研判矩阵，严禁混成一个「情绪分」。

---

## 四、TODO List

### 阶段 0：环境与决策确认

- [ ] **0.1** 确认新增独立 `sentiment` 数据源（而非并入 `search`）：热度/情绪是结构化数值序列，与 `search` 非结构化文本语义不同。
- [ ] **0.2** 确认消费方式：走 `DataSourceRouter.fetch_sentiment` HTTP 代理（禁止前端/主服务直连外部）。
- [ ] **0.3** 本文件即决策记录，落地后同步摘要到 `MEMORY.md`。

### 阶段 A：热度榜（ApeWisdom，✅ 已可用）

- [ ] **A.1** 新增 `data_subservice/_internal/sentiment/apewisdom.py`：封装 `GET https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}`。
- [ ] **A.2** 复用现有 `_get` 风格 + 超时 + 429/异常兜底（参考 `_internal/finnhub/__init__.py` 的 `error_category` 模式）。
- [ ] **A.3** 分页处理：当前约 11 页 × 100 条，提供 `page` 参数 + 可选抓全量 top N。
- [ ] **A.4** worker 注册 + `DS_CAPABILITIES=sentiment`。
- [ ] **A.5** 主服务 `router.py` 加 `fetch_sentiment` + 路由。
- [ ] **A.6** 单测：正常返回、异常兜底、分页、字段完整性。
- [ ] **A.7** 提交 PR。

### 阶段 B：多空情绪（❌ 暂无可用的免费源，待定）

- [ ] **B.1** 若未来找到新的免费/低价多空情绪源，先按 §2 教训**实测 Key 权限 + 端点存活**再接入。
- [ ] **B.2** 明确情绪分数语义与取值范围，归一化到系统统一约定（如 -1~1）。
- [ ] **B.3** 实现 `_internal/sentiment/<new-source>.py` + worker 注册 `action="SENTIMENT_SCORE"`。
- [ ] **B.4** 单测 + 限流退避（付费源尤需）。
- [ ] **B.5** 提交 PR。
- [ ] **B.6** 备选决策：若确认需要，评估机构级付费源（Social Market Analytics / RavenPack），单独立项。

### 阶段 C：信号接入研判层

- [ ] **C.1** 定义两个独立指标，严禁混淆：
  - **热度因子**（A 线）：`mentions` 环比变化 `(mentions - mentions_24h_ago) / mentions_24h_ago` → 「散户注意力突变」。
  - **情绪因子**（B 线，待源）：多空占比 / 情绪分数 → 「散户多空倾向」。
- [ ] **C.2** 接入 `AGENTS.md` §7 多空矩阵，热度因子与情绪因子作为独立的多头/空头行。
- [ ] **C.3** 与 `get_macro_sentiment_history`（VIX / P-C Ratio / Credit Spread）拼成「机构情绪 + 散户情绪」双层视图。
- [ ] **C.4** 前端展示需分别标注数据源与含义（热度 ≠ 情绪），避免误导。

### 阶段 D：收尾与文档

- [ ] **D.1** `MEMORY.md` 沉淀：数据源选型结论 + 三个源的验证失败记录（Finnhub 403 / StockGeist 502 / 富途无 API）。
- [ ] **D.2** `DEPLOYMENT_CHECKLIST.md` 补 `sentiment` 数据源接入说明 + 环境变量（ApeWisdom 免 Key）。
- [ ] **D.3** 更新 `.env.data-node.example` 与 `DS_CAPABILITIES` 说明（新增 `sentiment`）。
- [ ] **D.4** 全链路端到端验证 + 最终 PR。

---

## 五、关键提醒（写进清单顶部，避免后期踩坑）

1. **先验证 Key 权限 + 端点存活再写代码**（Finnhub 403 / StockGeist 502 的教训）。
2. **热度 ≠ 情绪**，两个指标分别定义、分别入矩阵，别混成一个「情绪分」自欺欺人。
3. **A 线（ApeWisdom）零门槛已可用，可先独立落地跑起来**，B 线等找到可靠源再上，不必等齐。
4. 本架构数据源「仅远程、无本地降级」，接入新源前务必评估其稳定性，避免把 502 级不稳源引入生产链路。

---

## 六、参考文献

- Finnhub API：`https://finnhub.io/api/v1/stock/social-sentiment`（免费档 403，已实测）
- ApeWisdom API：`https://apewisdom.io/api/`（免费无 Key，已实测调通）
- StockGeist API：`https://www.stockgeist.ai/stock-market-api/`（API 文档端点 502，已实测）
- 富途 Skills Hub：`https://www.futunn.com/skillhub`（社区情绪无公开 API）
- 2026 股票情绪 API 对比：`https://adanos.org/insights/blog/best-stock-sentiment-apis-2026/`
