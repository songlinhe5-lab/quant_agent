# TODO — 散户情绪数据源接入调研与计划

> 创建时间：2026-08-13
> 最后核对：2026-08-22（代码仍未开始）
> 状态：调研已完成，**阶段 A 已实现**；**阶段 B 核心（市场化 P/C 多空情绪）已随 CBOE 采集器 + sentiment_tracker 落地**，仅「散户社交多空占比」待定/付费决策（见 §三、阶段 B）
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

1. **「多空情绪」需分两层看，结论不同**：
   - **市场化多空情绪（看跌/看涨力量对比）= 免费且已落地**：期权 Put/Call Ratio 是权威代理。本仓已通过 CBOE 官方 Total P/C（`cboe_pc_ratio.py` 采集器 + `cboe_pc_daemon` 周期刷新至 `yf_macro_cache_^CPC`）接入 `SentimentTracker` 研判层（`models.SentimentRecord.pc_ratio`），与 VIX / Credit Spread 形成机构级多空视图；个股级 P/C 可由 `yfinance` 期权链免费补充（2026-08 实测 yfinance 期权链仍可用，GitHub 多活跃项目佐证）。**阶段 B 核心可行。**
   - **散户社交多空占比 = 仍无可靠免费源**：Finnhub 403、StockGeist 502、富途无 API、Utradea 停滞。若要真正的散户多空占比，只能上机构级付费源（Social Market Analytics / RavenPack，$299+/月），属另一决策，不在本期。阶段 A（ApeWisdom 热度）已覆盖散户注意力，「散户社交多空占比」维持待定。
2. **「散户热度/注意力」可立即落地**：ApeWisdom 免费、无 Key、已实测可用。
3. **热度 ≠ 情绪**：必须作为两个独立指标分别定义、分别入研判矩阵，严禁混成一个「情绪分」。

---

## 四、TODO List

### 阶段 0：环境与决策确认

- [x] **0.1** 确认新增独立 `sentiment` 数据源（而非并入 `search`）：热度/情绪是结构化数值序列，与 `search` 非结构化文本语义不同。*（2026-08-22 已落地：`_internal/sentiment/` + `sentiment_worker.py`，阶段 A 实现）*
- [x] **0.2** 确认消费方式：走 `DataSourceRouter.fetch_sentiment` HTTP 代理（禁止前端/主服务直连外部）。*（2026-08-22 已落地：`router.py` 加 `fetch_sentiment` + `sentiment_master` 节点，commit 79ef0ba）*
- [x] **0.3** 本文件即决策记录，落地后摘要沉淀到 `update_memory` 知识库（**勿写 `MEMORY.md`**：AGENTS.md §0 规定其为会话笔记、禁止默认加载，本仓记忆机制已迁移至 `update_memory`）。*（2026-08-22 已修正引用并完成重议）*

### 阶段 A：热度榜（ApeWisdom，✅ 已可用，2026-08-22 已实现）

- [x] **A.1** 新增 `data_subservice/_internal/sentiment/apewisdom.py`：封装 `GET https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}`。
- [x] **A.2** 复用 `_get` 风格 + httpx 超时 + 429(`rate_limit`)/异常兜底（对齐 finnhub `error_category` 模式）。
- [x] **A.3** 分页处理：提供 `page` 参数 + `top_n` 自动翻页抓全量（受 `_MAX_PAGES` 限，默认 11 页 × 100 条）。
- [x] **A.4** worker 注册（`sentiment_worker.py` + `main.py` `_WORKER_IMPORTS`）；`DS_CAPABILITIES` 部署时显式声明 `sentiment`。
- [x] **A.5** 主服务 `router.py` 加 `sentiment_master` 节点 + `fetch_sentiment` + `_SENTIMENT_ACTION_MAP`；后端 `adapters/sentiment.py` 经 `DataSourceRegistry` 注册。
- [x] **A.6** 单测：正常返回、异常兜底、分页、字段归一化、中途失败部分返回——`tests/test_apewisdom.py` 5 passed。
- [ ] **A.7** 提交 PR。

### 阶段 B：多空情绪（✅ 可行：市场化 P/C 已免费落地；散户社交多空占比仍待定）

> 2026-08-22 调研修正：原结论"暂无可用的免费源"系将「多空情绪」窄化为「散户社交多空占比」。
> 实际上**多空情绪的本质是看跌/看涨力量对比**，期权 Put/Call Ratio 是免费、权威、已落地的代理指标，
> 且本仓已实现（CBOE 全市场 P/C 已接入 `sentiment_tracker` 研判层）。仅「散户社交多空占比」一项仍无可靠免费源。

- [x] **B.0** 市场化多空情绪已落地：CBOE Total P/C Ratio（`cboe_pc_ratio.py` 采集器 + `cboe_pc_daemon` 周期刷新至 `yf_macro_cache_^CPC`）已由 `SentimentTracker` 每小时打点落库（`models.SentimentRecord.pc_ratio`），与 VIX / Credit Spread 形成机构级多空视图。*（2026-08-22 调研确认，代码早已存在）*
- [x] **B.1** 个股级多空情绪增强：✅ **2026-08-22 实现，数据源改用 Futu 而非 yfinance**。零幻觉验证：`yfinance` 期权链 **2026-08-22 实测全局限流**（`YFRateLimitError: Too Many Requests`，AAPL+MSFT 均失败），故弃用；改用 **Futu `get_option_underlying_overview`（P0.5 已实现，OpenD 实测返回 call_volume=924462/put_volume=610806）** 派生个股 P/C。实现 `business/option.py::get_option_underlying_put_call`（基于 overview 的 call/put volume）+ HTTP 端点 `/option-underlying-put-call`。实测 AAPL P/C=0.6607 → 偏多。
- [x] **B.2** P/C Ratio 语义与归一化：✅ 文档约定阈值落地：**P/C > 1.2 偏空 / < 0.8 偏多 / 中间中性**，映射 **-1(极空)~+1(极多)**；`get_option_underlying_put_call` 返回 `pc_ratio`/`score`/`signal`，空数据降级不臆造。
- [x] **B.3** 单测：✅ `TestUnderlyingPutCall` 5 例（偏空/偏多/中性/无量仓降级/错误透传），`test_option_full_dim_service.py` 共 **17 例全过**。（注：yfinance 限流故不再做 yfinance 限流退避，改用 Futu 已接入数据源）
- [ ] **B.4** 提交 PR（本次 B.1~B.3 已 commit `B.1 个股P/C`，待标注）。
- [ ] **B.5** 散户社交多空占比（原 B.6）：仍维持待定。若确认需要，评估机构级付费源（Social Market Analytics / RavenPack，$299+/月），单独立项。未经实测 Key 权限 + 端点存活不接入。

### 阶段 C：信号接入研判层

- [x] **C.1** 定义两个独立指标，严禁混淆：
  - **热度因子**（A 线）：`mentions` 环比变化 `(mentions - mentions_24h_ago) / mentions_24h_ago` → 「散户注意力突变」。✅ **2026-08-22 已接入研判层**：`apewisdom._normalize_item` 已算 `mentions_delta_pct`；`SentimentRecord` 新增 `retail_heat_change_pct`/`retail_heat_total` 字段（create_all 自动建表）；`sentiment_tracker._run_once` 经 `fetch_sentiment("trending")` 拉取 ApeWisdom top-N 榜 → 派生市场级热度因子（delta 均值 + 总 mentions）→ 落库。**修复 bug**：ApeWisdom API 真实响应键为 `results`（非 `data`），原代码读 `data` 导致 count=0，已修复 + 兼容旧键。实测 top10 热度环比均值=0.4137。
  - **情绪因子**（B 线，待源）：多空占比 / 情绪分数 → 「散户多空倾向」。（B.1 已用 Futu 个股 P/C 落地部分）
- [ ] **C.2** 接入 `AGENTS.md` §7 多空矩阵，热度因子与情绪因子作为独立的多头/空头行。
- [ ] **C.3** 与 `get_macro_sentiment_history`（VIX / P-C Ratio / Credit Spread）拼成「机构情绪 + 散户情绪」双层视图。
- [ ] **C.4** 前端展示需分别标注数据源与含义（热度 ≠ 情绪），避免误导。

### 阶段 D：收尾与文档

- [x] **D.1** 沉淀选型结论到 `update_memory` 知识库（**勿写 `MEMORY.md`**：AGENTS.md §0 规定其为会话笔记、禁止默认加载）+ 在本文档 §二保留三个源验证失败记录（Finnhub 403 / StockGeist 502 / 富途无 API）。*（2026-08-22 已完成：引用修正 + 重议）*
- [x] **D.2** `DEPLOYMENT_CHECKLIST.md` 补 `sentiment` 数据源接入说明 + 环境变量（ApeWisdom 免 Key）+ 问题 7 全链路验证/排错。*（2026-08-22 已完成）*
- [x] **D.3** 更新 `.env.data-node.example` 与 `.env.example` 的 `DS_CAPABILITIES` 说明（主节点能力集 + 全量能力集 + US-MASTER 示例均含 `sentiment`）。*（2026-08-22 已完成）*
- [x] **D.4** 全链路端到端验证脚本已写入 `DEPLOYMENT_CHECKLIST.md` 问题 7（S1 节点实测 3 步）+ 代码已进 PR #359。*（2026-08-22 已完成文档侧；S1 实测待部署后执行）*

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
