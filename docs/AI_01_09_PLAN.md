# AI-01~09 产品 AI 渗透功能 · 开发拆解与接口契约

> 状态：规划文档（2026-07-26 初版）
> 目标：将 docs/TODO.md 中 AI-01~09 九大产品 AI 渗透任务拆解为可执行的开发 plan + 接口契约。
> 执行纪律：遵循 Vibe Coding，每条功能改动即 commit，不得累积；所有 LLM 输出严守零幻觉红线。

---

## 一、现状一句话

九大功能的 **LLM 底座**（路由/降级/Eval/RAG）与大部分**数据路由**已就绪；真正缺的是"把底座接到前端 UI 的最后一公里"——要么组件写完没挂上画布（AI-01），要么后端端点还是 mock（AI-02 search），要么压根没建 AI 端点（AI-04~09）。

## 二、可复用能力底座（已 ✅，九大功能零成本调用）

| 底座 | 位置 | 能力 | 被谁复用 |
|---|---|---|---|
| `LLMService` | `backend/services/llm_service.py` | `ModelTier`(LIGHTWEIGHT/STANDARD/FLAGSHIP) + `generate_pydantic` 结构化输出 + 主供 3 次失败自动降级 Ollama | AI-01~09 全部 |
| `EvalFramework` | `backend/services/eval_framework.py` + `eval_runner` | 数字准确率 0.4 / 引用溯源率 0.3 / DSL 合规率 0.3 加权 + 55 例 Golden Dataset + `eval.yml` CI | AI-01/02/04~08 质量校验 |
| `RAGGovernance` | `backend/services/rag_governance.py` | Embedding 版本 + 分类 TTL + 检索质量监控(相似度<0.6 连 10 次告警) | AI-01/06/08 检索底座 |
| 数据路由 | `backtest`/`alpha158`/`factor`/`risk`/`oms`/`paper`/`macro`/`alert`/`preferences` | 真实行情/因子/风险/宏观数据 | AI-02/03/04/05/06/07/08/09 |

## 三、执行顺序

- **Phase 0（基础设施）**：AI-09 推送偏好底座（AI-04~08 的推送全依赖它）
- **Phase 1（P1 修复+补全）**：AI-01 画布挂载 / AI-02 search 去 mock + 异常值预警 / AI-03 Tear Sheet 摘要 + 过拟合检测
- **Phase 2（P1 新建）**：AI-04 执行预检 / AI-05 风险推送
- **Phase 3（P2 新建）**：AI-06 分诊 / AI-07 教练 / AI-08 事件推演

---

## Phase 0 · AI-09 推送偏好底座（P2，必须先建）

**现状**：`settings-content.tsx` 仅 `AiNarratorSettingsCard`（AI-01 专属）；`preferences_router` 有用户偏好存储，但无"模块级 AI 开关 + 触发阈值"schema。

**Plan**
1. `PreferencesModel` 扩 `ai_push: dict`：`{ module: "ai01".."ai08", enabled: bool, threshold: float|null }`。
2. 新增 `PUT /api/v1/preferences/ai-push`、`GET /api/v1/preferences/ai-push`。
3. 前端抽 `useAiPushPrefStore`(persist)，取代散落开关；AI-01~08 推送逻辑统一读此 store。

**接口契约**
```
PUT /api/v1/preferences/ai-push
{ "prefs": [ { "module": "ai01", "enabled": true, "threshold": 2.0 },
             { "module": "ai08", "enabled": true, "threshold": null } ] }
→ 200 { "updated": 9, "ts": "ISO8601" }
GET /api/v1/preferences/ai-push → { "prefs": [...] }
```

---

## Phase 1 · P1 半成品修复

### AI-01 市场指挥中心·异动解说员（P1）
**现状**：`narrator-bubble`/`pattern-detect`/`order-book-large-order-hint`/`anomaly-flash` 落地，但 `lightweight-chart-canvas.tsx` **未挂载**；形态胜率前端自算未联动解说。

**Plan**
1. 在 `lightweight-chart-canvas.tsx` K 线 overlay 挂载上述组件，由 `useAiPushPrefStore.ai01` 开关控制。
2. `POST /ai/narrate` 已真实驱动，补可选 `include_pattern_winrate`，让气泡联动形态历史胜率（复用 `pattern-detect` 回测，不写死）。
3. 失败降级文案保留，严禁写死示例行情。

**接口契约（扩展已有）**
```
POST /api/v1/ai/narrate  (已有)
NarrativeRequest+{ "include_pattern_winrate": bool }
→ NarrativeResult+{ "pattern_winrate": float|null }
```

### AI-02 智能选股器·因子顾问（P1）
**现状**：`/factor/suggest` 真数据 ✅；`/factor/search` 的 `_search_single_factor` **是 mock**（`mock_sharpe=1.5-i*0.1`）；缺异常值预警。

**Plan**
1. `grid_search_factors._search_single_factor` 接真实 `backtest_router` 回测，删除 mock 分支（零幻觉红线）。
2. 新增异常值预警端点：吃 `get_fundamental_data` 的 PE/PB/ROE，检测一次性收益扭曲（扣非 PE 与 PE 偏离 > 阈值）→ LLM 中文预警。

**接口契约**
```
POST /api/v1/factor/search        // 改为真实回测驱动，删除 mock
FactorSearchRequest{ symbol, factors:[...] }
→ results:[{ "factor_name", "best_params", "best_sharpe"(real), "best_return"(real) }]

POST /api/v1/factor/anomaly-check  NEW
{ "symbol": "AAPL" }
→ { "pe": 18.2, "pe_ttm_ex_nonrecurring": 31.5,
    "distortion": true, "advice": "⚠️ 疑似一次性收益扭曲，建议看扣非 PE", "source": "akshare" }
```

### AI-03 回测工坊·报告解读员（P1）
**现状**：`alpha158`/`eval` 路由齐全；无 Tear Sheet 摘要端点、无过拟合检测端点、前端无解读面板。

**Plan**
1. 新增 `POST /api/v1/backtest/interpret`：吃回测结果 → `LLMService(FLAGSHIP)` 生成 ≤80 字摘要，须含"收益是否来自杠杆而非 Alpha"判别。
2. 新增过拟合检测：扫描参数敏感性，差异 >40% 触发预警（纯计算）。
3. 前端 `backtest-interpret-panel.tsx` 接两端点，显示于 Tear Sheet 顶部。

**接口契约**
```
POST /api/v1/backtest/interpret  NEW
{ "symbol":"AAPL", "annual_return":0.23, "sharpe":0.9, "mdd":0.18, "leverage":2.1 }
→ { "summary":"年化23%但Sharpe仅0.9，收益主要来自2.1x杠杆而非Alpha",
    "source":"llm", "confidence":0.82 }
POST /api/v1/backtest/overfit-check  NEW
{ "param_sweep":[{"param":"lookback","sharpe":[1.6,0.9,1.5]}] }
→ { "overfit": true, "max_sensitivity":0.44, "threshold":0.40 }
```

---

## Phase 2 · P1 新建项

### AI-04 OMS·执行风控官（P1）
**现状**：`oms_router` 无 AI 端点；无 AI 预检弹窗。

**Plan**
1. 新增 `POST /oms/precheck`：规则(VIX>25→建议减半/限价) + `LLMService(STANDARD)` 混合预检，吃 `macro` VIX。
2. 新增 `GET /oms/position-health/{id}`：对比入场逻辑信号，失效则建议止盈（复用 `alpha158` 信号）。
3. 前端 `order-confirm-modal` 注入 AI 预检区块，由 `ai04` 开关控制。

**接口契约**
```
POST /api/v1/oms/precheck  NEW
{ "symbol":"AAPL", "side":"buy", "qty":100, "order_type":"market" }
→ { "vix":28.0, "warning":"⚠️ VIX=28 高波动，建议减半仓位或改限价单",
    "suggest_qty":50, "suggest_type":"limit", "source":"rule+llm" }
GET /api/v1/oms/position-health/{position_id}  NEW
→ { "signal_valid":false, "advice":"AAPL 已偏离入场逻辑，建议止盈", "entry_logic":"MA20 突破" }
```

### AI-05 风控面板·风险预警员（P1）
**现状**：`risk_router` 压测/暴露/相关性齐全；缺维度变红主动推送 + LLM 预警。

**Plan**
1. 前端雷达图维度变红时调 `POST /risk/alert-narrative`，吃 `risk/dashboard` → LLM 预警。
2. 复用 `alert_router` 推送通道 + `ai05` 开关。
3. 压测情景推荐：读 `risk/stress-test/scenarios`，按持仓 Beta 排序 Top3。

**接口契约**
```
POST /api/v1/risk/alert-narrative  NEW
{ "dimension":"concentration", "score":82, "portfolio_beta":1.1 }
→ { "alert":"集中度82/100，若纳指回调5%组合预计-3.4%", "scenarios":["2008","2020","2022"] }
```

---

## Phase 3 · P2 新建项

### AI-06 告警中心·分诊员（P2）
**Plan**：新增 `POST /alert/triage`，吃 `alert/events` + `macro/sector-fund-flow`，LLM 做板块关联分析 + 多告警优先级排序（止损>突破）；排序质量用 `EvalFramework` 校验。

**接口契约**
```
POST /api/v1/alert/triage  NEW
{ "events":[{"symbol":"AAPL","type":"breakout"},{"symbol":"TSLA","type":"stop_loss"}] }
→ { "grouped":"AAPL+3只科技股同日突破→板块性行情", "priority":["TSLA_stop_loss","AAPL_breakout"] }
```

### AI-07 纸面组合·实盘教练（P2）
**Plan**：新增 `POST /paper/{id}/readiness` + `POST /paper/{id}/drift-warning`，基于 `paper/compare` + `llm_service` 生成实盘就绪评估、纸面 vs 回测偏差预警（Sharpe 差异归因滑点）。

**接口契约**
```
POST /api/v1/paper/{portfolio_id}/readiness  NEW
{ "days":30, "sharpe_paper":0.8, "sharpe_backtest":1.6 }
→ { "ready":false, "reasons":["样本仅30天","Sharpe偏差源于未计滑点"], "score":62 }
```

### AI-08 宏观数据中心·事件推演（P2）
**Plan**：新增 `POST /macro/event-inference`（高危事件推演卡，复用 `sentiment_service` + `llm_service`）；新增 `POST /macro/vix-beta-impact`（VIX×组合 Beta→日波动测算，复用 `alpha158.beta`）。

**接口契约**
```
POST /api/v1/macro/event-inference  NEW
{ "event":"FOMC", "scenario":"hike_25bp", "holdings":["00700.HK","AAPL"] }
→ { "inference":"FOMC 加息25bp→港股科技预计-2~3%", "confidence":0.7 }
POST /api/v1/macro/vix-beta-impact  NEW
{ "portfolio_beta":1.1, "vix_delta":5 }
→ { "daily_pnl_impact":"-¥8,200", "unit":"CNY" }
```

---

## 四、红线与验收（贯穿九条）

- **零幻觉**：所有 LLM 输出必须基于 Tool 真实数据，无数据则降级/空态，**禁止写死示例行情**。AI-02 search 的 mock 是头号必清项。
- **质量门**：AI-01/02/04~08 自然语言输出上线前各扩一类 Golden Dataset，接 `eval.yml` CI。
- **开关统一**：九大功能推送/启用全部走 `useAiPushPrefStore` + `ai0X` 开关，不散落 localStorage。
- **验收标准**：每条功能交付 = 后端真实端点(非 mock) + 前端接真实数据面板 + 对应 Eval 用例绿 + tsc 零错误。

## 五、提交节奏

- 每完成一条（或一条内的一个可独立验证的子任务）即 `git commit`，commit message 带 `AI-0X` 前缀。
- Phase 0 先于一切；Phase 1 中优先清掉 AI-02 mock（承接历史清 mock 主题）。
