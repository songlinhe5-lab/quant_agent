# 运维探针脚本 (Diagnostic Probes)

本目录收纳**直接对接外部数据源 SDK / API** 的运维诊断脚本（区别于 `scripts/` 根目录的
生产流水线脚本如 `run_cli.py`、`start_all.py`、`benchmark_*`、`locust_*`、`migrate_*`）。

## 归属说明（BE-ARCH-07o）

这些脚本**不是生产代码路径**，不参与主服务 `backend/services/` 的远程联邦架构
（统一经 `DataSourceRouter` 调 `data_subservice`）。它们仅用于：

- 验证某个第三方数据源（Yahoo / AKShare / Tushare / Futu / Finnhub / Tavily / Sina）的
  连通性、schema 变更、配额/权限、延迟等运维排查；
- 在 `data_subservice` 未覆盖或需要裸调 SDK 复现问题时做对照诊断。

## 门禁豁免

`backend/tests/test_be_arch07n_services_boundary.py` 的强门禁只扫描
`backend/services`、`backend/routers`、`backend/core`、`hermes_agent`，**不覆盖本目录**，
因此这些脚本的 SDK 直连不会触发架构守门失败。但这不代表可以随意新增生产依赖——
任何生产路径的数据获取仍须走 `DataSourceRouter` 远程代理。

## 脚本清单

| 脚本 | 直连源 | 用途 |
|---|---|---|
| `test_yf.py` / `test_yf2.py` / `test_yf_batch.py` | yfinance | Yahoo 行情连通性 |
| `futu_fetch.py` | futu + yfinance | Futu OpenD 宿主裸调 + Yahoo 对照 |
| `test_futu_screen_direct.py` | futu | Futu 选股器直连诊断 |
| `test_screener_cases.py` | futu | 选股用例复现 |
| `probe_akshare_alts.py` / `probe_local_proxy.py` / `probe_sina_schema.py` / `verify_quote_sina.py` | akshare | AKShare / 新浪 schema 探针 |
| `test_local_em_direct.py` | akshare | 本地 EM 直连诊断 |
| `probe_tushare_diag.py` | tushare | Tushare pro_api 诊断 |
| `test_finnhub_permissions.py` / `test_finnhub_dashboard_data.py` / `test_finnhub_rest_news.py` | finnhub REST | Finnhub 权限/新闻/insider 诊断 |
| `test_tavily_search.py` / `test_google_search.py` | tavily / google | 搜索源诊断 |
| `verify_macro.py` / `sync_minute_data.py` / `export_all_tickers.py` | yfinance | 宏观/K线/标的基础数据裸取（诊断用） |

## 使用约定

- 运行前确保对应 SDK 已在当前 Python 环境安装（或 `uv`/`pip` 临时装好）；
- 这些脚本**不得**被 `backend/` 任何生产模块 `import`；
- 新增诊断脚本请直接放本目录，并补充上表条目。
