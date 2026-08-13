# TODO — Futu 预测市场（事件合约）评估与接入计划

> 创建时间：2026-08-13
> 状态：评估已完成，**代码未开始**（后期开动）
> 触发来源：富途 Futu API v10.9 预测市场（Event Contract）能力评估
> 参考文档：`https://openapi.futunn.com/futu-api-doc/quote/event-contract-overview.html`

---

## 一、评估结论（先给结论）

**值得接，但定位必须清楚：只当「美股宏观事件的市场定价概率」数据源，不当交易标的。优先级 P2（低于组合期权行情、财务三大表）。**

**一句话**：事件合约是唯一能给出「离散事件隐含概率」的数据源（YES 价格 = 市场对事件发生的概率），与宏观风控层天然互补；但下单接口缺失（纯 read-only）、订阅-推送范式错配、市场覆盖偏美股事件，工程成本高、增益有限。

---

## 二、能力边界（官方文档实测结论）

### 2.1 本质

事件合约（Event Contract）= 预测市场（对标 Kalshi / Polymarket），针对**离散事件**做 YES/NO 二元交易。事件类型：选举 / 经济数据 / 赛事。

合约层级：**分类（Category）→ 赛事筛选（Competition）→ Series → Event → Contract**。

### 2.2 已支持（行情侧完整）

| 数据类型 | 接口 | 说明 |
|---------|------|------|
| 实时快照 | `get_event_contract_snapshot` | 最新价、累计成交量、YES/NO 买卖一档 |
| 盘口 | `get_event_contract_order_book` | 多档 YES/NO 买卖盘（需先订阅） |
| 实时 K线 | `get_event_contract_kline` | 需先订阅对应 K 线类型 |
| 历史 K线 | `request_history_event_contract_kline` | 拉历史 |
| 逐笔 | `get_event_contract_ticker` | 需先订阅 TICKER |
| 订阅 | `subscribe_event_contract` / `unsubscribe_*` | 推送回调（HandlerBase 类） |
| 发现 | `get_event_contract_category` → `series_list` → `event_list` → `get_event_contract` | 分类→赛事→Series→Event→Contract |
| 组合 | `get_valid_combo_list` / `request_combo_quotes` | Combo 组合询价 |

### 2.3 缺失（硬约束）

- ❌ **无交易下单接口**（官方文档仅行情侧，未列 `place_event_contract_order`）。
- ❌ 未明确支持市场/标的（大概率以美股事件为主）。
- ❌ 未说明权限要求（需先验证 OpenD 账户是否开通事件合约行情权限）。

---

## 三、核心价值与契合点

- **隐含概率**：YES 价格 = 市场对「该事件发生」的概率，是真金白银定价，比 VIX 推演 / 新闻猜政策硬核。
- **契合宏观风控**：AGENTS.md §5 宏观监控（FOMC/非农/CPI/选举）当前靠 VIX/P-C Ratio/Credit Spread + 新闻舆情，缺「离散事件市场定价概率」这一层。事件合约恰好补齐。

---

## 四、TODO List

### 阶段 P0：发现链 + 快照（ROI 最高，同步 REST 拉取，先做）

- [ ] **P0.1** 验证权限：确认 OpenD 账户是否开通事件合约行情权限（先验证再写代码，同 Finnhub 403 教训）。
- [ ] **P0.2** 实现发现链：`get_event_contract_category` → `get_event_contract_series_list` → `get_event_contract_event_list` → `get_event_contract`。
- [ ] **P0.3** 实现快照：`get_event_contract_snapshot`（最新价/累计成交量/YES/NO 一档）。
- [ ] **P0.4** 接入 `futu_worker.py` 的 `_FUTU_ACTION_MAP`：新增 action（如 `EVENT_CONTRACT_SNAPSHOT` / `EVENT_CONTRACT_DISCOVERY`）。
- [ ] **P0.5** 主服务 `adapters/futu.py` 的 `capabilities` 声明 + `router.py` 路由。
- [ ] **P0.6** 接入 `@with_global_retry` + `cache_mgr` 缓存。
- [ ] **P0.7** 单测 + 提交 PR。
- [ ] **P0.8** 研判层接入：把「FOMC/非农/CPI/大选」市场定价概率喂进宏观风控层（AGENTS.md §5）。

### 阶段 P1：订阅推送（异步回调，工程量大，暂缓）

- [ ] **P1.1** 评估是否有实时盘口/K线/逐笔的消费场景（当前无，默认不接）。
- [ ] **P1.2** 若接：新增 `EventContract*HandlerBase` 回调桥接（参考现有 `push_handler.py` 的 OpenD 推送桥接经验，但事件合约是另一套回调注册机制）。
- [ ] **P1.3** 单测 + 提交 PR。

### 阶段 P2：交易侧（待 Futu 开放下单接口）

- [ ] **P2.1** 若 Futu 后续开放事件合约下单接口，再评估交易接入。
- [ ] **P2.2** 严守 AGENTS.md §6 沙箱约束（默认 SIMULATE）。

### 阶段 P3：文档对齐

- [ ] **P3.1** `MEMORY.md` 沉淀：事件合约能力边界（行情侧完整、交易侧缺失）+ 隐含概率价值。
- [ ] **P3.2** `AGENTS.md` §5 宏观监控补充「事件合约隐含概率」作为新信号源。
- [ ] **P3.3** `DEPLOYMENT_CHECKLIST.md` 补事件合约接入说明 + 权限门槛。

---

## 五、落地关键点（架构红线）

1. **仅远程**：下沉 `data_subservice`，主服务经 `DataSourceRouter.fetch_futu()` HTTP 代理，禁主服务直连 OpenD。
2. **先验证权限再写代码**：事件合约权限不明，接入前先实测（P0.1）。
3. **范式错配**：快照/发现是同步 REST 拉取（可直接复用现有结构）；盘口/K线/逐笔是订阅-推送（需新增回调桥接），**不要混在一起做**。
4. **零幻觉**：隐含概率必须来自 `get_event_contract_snapshot` 真实返回，严禁自行估算。
5. **定位**：只当「美股宏观事件概率」数据源，非交易标的。

---

## 六、参考资料

- 预测市场接口总览：`https://openapi.futunn.com/futu-api-doc/quote/event-contract-overview.html`
- 现有 push 桥接参考：`data_subservice/futu_src/push_handler.py`
- 现有期权/行情实现：`data_subservice/futu_src/option_fund_handler.py`
- 适配器：`backend/services/datasource/adapters/futu.py`
