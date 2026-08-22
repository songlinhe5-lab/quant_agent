# MEMORY — 决策备忘（禁止默认加载）

> **禁止 `@MEMORY.md`。** 本文件不是编码宪法。写代码看 `AGENTS.md`。
> 需要某条决策时 **Grep 关键词**，不要整本灌入。
> 历史全文：`git log -p -- MEMORY.md`。已完成的 Phase 文件清单 / 测试计数 / commit hash 不在此重复。

---

## 1. 数据源物理隔离（2026-08-06）

主服务镜像 **不得** 安装数据 SDK（`futu-api` / `tushare` / `akshare` / `yfinance`）。SDK 只在 `data_subservice` 与 `pyproject.toml` extra：`datasource-cn` / `datasource-us` / `datasource-us-aux`。运行时只经 `DataSourceRouter` HTTP。

## 2. 子服务职责红线（2026-08-06 拍板）

`data_subservice` **只做**：① SDK/WS/OpenD 连接 ② 限流/熔断/健康/自愈 ③ `/ds/{source}/{action}` + `/metrics`。

**禁止**在子服务写业务编排（LLM 秒评、通知、分片、宏观聚合、信号）。判定：**获取+保障 = 子服务；消费后加工 = 主服务**。Finnhub 秒评/通知留主服务；FMP daemon 整体下沉。

连接层全远程：主服务无本地 SDK / WS / 直连外网 API。失效在监控如实显示，无本地降级。

未闭环（非阻断）：akshare 南向/北向定时采集补进 worker；FMP `/metrics` credit 看板。

## 3. 镜像 extra 与观察方式（2026-08-11）

重建主节点镜像必须 `--build-arg DS_EXTRA=datasource-us`，否则 Dockerfile 默认 `cn` → `No module named 'futu'`。本地 tag 必须与 compose 引用同名（`...data-subservice:us`）；`up` 必须 `--env-file .env.data-node`。

**禁止** `docker exec ... import futu_service` 判断连通——exec 是新进程，单例未 connect。查常驻：`GET /futu/status` 或 `GET /health`。

## 4. `asyncio.create_task` 必须强引用（2026-08-12）

裸 `asyncio.create_task(watchdog.start())` 无变量持有 → 下次 GC 取消任务 → 看门狗静默停摆。长生命周期后台协程必须挂模块全局或对象属性。短生命周期、函数内 await 完的不受此限。

同样禁止 `docker exec import get_watchdog` 看 `running`——新进程未 start。

## 5. 同机服务名 / 跨机 Tailscale（2026-08-12）

保持 Docker bridge，**不用** `network_mode: host`（SEC-16）。同 VPS：共享 `quant-internal`，`FUTU_REMOTE_URL=http://data-subservice:8001`。跨 VPS：Tailscale IP + HMAC，不用服务名。

容器内 `127.0.0.1` 连不上宿主 OpenD；用 `host.docker.internal`，且 OpenD 必须听 `0.0.0.0:11111`。主服务容器打公网 IP:8001 会 `reachable:false` 熔断（Issue #289 已用方案 A 闭环）。

中转 registry **只缓存北京 `:cn`**。主服务 / `:us` / `:us-aux` 走 GHCR。

## 6. HMAC 403（2026-08-13）

`verify_hmac` 三关：缺头 → 时间戳差 >300s（**先于**签名）→ 签名失败。

真因两次都是配置：① `.env.data-node` 把 `<与主节点一致的 HMAC 密钥>` **字面量**当密钥；`printenv` 回显那段中文不是打码。② `echo >>` 粘到无换行的末行，密钥进了 `TZ=` 值，容器回退 `change-me-in-prod`。

先 `printenv DATA_SOURCE_HMAC_SECRET`，再确认独立成行。追加用 `printf 'KEY=val\n'`。`DATA_SOURCE_ALLOWED_IPS` 代码里无引用。

## 7. 「测试连接」失联（2026-08-13）

futu / finnhub 的 `health()` **都是**看 `node.status`，不打上游、不看 WS。看板「futu 挂、finnhub 通」是上游稳定性差，不是探测方式不同。全部测试连接会把 OpenD 节点 `error_count` 打爆。已加全局间隔 + per-source 锁 + 前端串行；不要给某源开 `health()` 例外。

## 8. Cloudflare Pages 前端域名（2026-08-14）

`VITE_API_BASE_URL` **必须** `https://quant-api.stephenhe.com/api/v1`。写成 `quant.stephenhe.com` → REST 被拦（大盘空白）+ `/auth/refresh` 失败清 token（假踢登录）。仓库无 `.env.production`，只在 Pages 构建变量。改完必须走会 deploy 的 CI（develop push 只 build）。WS 用 `getWsBaseUrl()` 跟 REST origin。

## 9. 北京直连 GHCR 无效（2026-08-15）

MTU=1450 **解决不了**北京拉 GHCR。TLS 握手正常，blob 0 字节（Azure CDN 跨境实质阻断）。北京必须走 S1 registry `100.102.223.44:5000/...:cn`。勿把 BJ 镜像源改回 `ghcr.io`。

## 10. Futu 基本面接口族（2026-08-22）

**真相**：`get_fundamental`（`option_fund_handler.py`）底层是 `get_market_snapshot` 快照，**只有 5 个估值字段**（company_name/trailing_PE/price_to_book/dividend_yield/market_cap）——是「假基本面」，ROE/做空比例等宣传字段底层拿不到。要真基本面走 `FINANCIALS`（财务三大表）+ `VALUATION`。

**P1 接口族已接入**（`option_fund_handler.py`，零幻觉实跑验证）：`FINANCIALS`（get_financials_statements，statement_type 传整数 1~4 + financial_type 大写枚举）、`VALUATION`、`RATING_SUMMARY`（rating_dimension_type=INSTITUTION/ANALYST，rating 在 rating_item_list 内）、`REVENUE_BREAKDOWN`（financial_type 大写 ANNUAL）、`SHORT_INTEREST`（3 元组）、`SHAREHOLDERS_*`/`INSIDER_*`（6 方法）、`CORP_ACTIONS_*`（dividends/buybacks/stock_splits，buybacks 仅港股/A股）。**SDK 10.10 命名与文档不同**：`get_insider_trade_list`（非 transaction）、`get_corporate_actions_{dividends,buybacks,stock_splits}`（非通配 `_*`）。全链路 handler→service→worker→adapter→router。

**选股因子 P2**：`screener_handler.py` 无硬白名单，因子可用性由 futu SDK 枚举决定（`get_enum` 透传）。官方特色因子 `SHORT_POSITION`/`ANALYST_RATING`/`ANALYST_TARGET_PRICE`/`RISE_PROB` 等已在 `backend/services/screener/constants.py` 登记（`_VALID_FIELDS` + `_TYPE_ENFORCEMENTS`）。⚠️ **option/broker 类因子选股实测 `NN_ProtoRet_SvrFailed`**（服务器端不支持，勿登记进 `_TYPE_ENFORCEMENTS` 强制纠偏）。⚠️ **kline_shape 的 period 须传整数**（Period.DAY=11），传 KLType 枚举会 `int('K_DAY')` 报错——已修复用 `get_period()`。

## 11. 新马日市场暂缓 + 组合期权接口族（2026-08-22）

**新马日（SG/MY/JP）是长尾，暂不投入**。核查：全库（排除 node_modules）无任何 SG/MY/JP 策略线/研报/前端消费场景；底层 `quote_handler`（市场校验含 SG/JP）+ `screener_handler`（ScrMarket JP/SG）+ `format_ticker`（识别 JP./SG. 前缀）已能处理 SG/JP 代码——**能取数但无消费场景，无增量价值**。待有真实需求再启（行情走 quote_handler、交易走 trade_handler，参考 HK/US 路径）。

**组合期权（`option_fund_handler.py`，P0/P0.5 全部 OpenD 实跑零幻觉）**：
- **P0 三件套**：`get_option_strategy`（策略定义，正股入参）+ `get_option_strategy_analysis`（损益分析，实测宽跨式 max_loss=-10116/breakeven=[103.84,311.16]，**禁 Black-Scholes 近似**）+ `get_option_quote`（38 列快照）。⚠️ `option_legs` 每元素须为 `OptionStrategyLeg` 对象（code/action/quantity），字符串报 `each item must be OptionStrategyLeg`。
- **P0.5 全维**：`get_option_underlying_his_volatility`（HV 时间序列）/`get_option_underlying_overview`（20 列 iv_rank+multi-hv）/`get_option_market_statistic`（Put/Call 比）/`get_option_zero_dte_screener`+`contract`（0DTE）/`get_option_earnings_screener`（财报期权）/`get_option_seller_screener`（卖方）/`get_option_exercise_probability`（行权概率）。⚠️ 枚举：`OptionMarket`=US_SECURITY、`SellerType`=COVERED_CALL、`OptionStatisticDataType`=VOLUME；`zero_dte_contract` 入参需 screener 的 `chain_info`。
- **business 层聚合**：`backend/services/datasource/business/option.py` 8 方法 + `get_option_put_call_panel`（P/C 比派生 latest/avg_5d/signal，<0.7 偏谨慎/>1.0 偏乐观，空数据降级不臆造）；`routers/market.py` 9 个端点。
- **P1 组合交易（骨架，沙箱）**：`trade_handler.py` 的 `place_combo_order`/`comboorder_tradinginfo_query`，`_resolve_trd_env` 默认 SIMULATE，仅 `REAL_TRADE_EXECUTE=1` **且** `force_real=True` 才 REAL；`ComboLeg` 字段=code/trd_side/qty_ratio/position_id/pred_side。OMS 实盘未实装，SIMULATE 盘推演。

## 12. 另类数据 ALT-01~03 阻塞暂缓（2026-08-22）

`TODO-ops.md` 的 3 项另类数据**均受外部 API 凭据阻塞，暂缓**。核查：全库配置文件**零命中** Reddit/X/链上/财报音频凭据，按零幻觉红线「先验证数据源可用再写代码，禁 mock」，不可盲写。
- **ALT-01** Reddit WSB + X 散户情绪：需 `REDDIT_CLIENT_ID/SECRET` + X `BEARER_TOKEN`。现有 `data_subservice/_internal/sentiment/apewisdom.py`（热议榜）已部分覆盖散户热度。待凭据就绪可做（最接近可启动，需先权限验证）。
- **ALT-02** 财报电话会议音频情感分析：需财报音频数据源（Seeking Alpha/IR）+ ASR + 声纹/语气模型，**重工程 + 数据源未就绪**，ROI 最低。
- **ALT-03** 链上大资金追踪：需链上数据源 key（Glassnode/交易所 API），且加密资产是项目长尾（同新马日无消费场景）。
