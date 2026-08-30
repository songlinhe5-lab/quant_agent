# 系统总体概览

本文档用于描述当前系统的整体架构和目录结构，帮助开发者快速了解项目全貌。

> 📋 **工程 Review 汇总**：所有架构审计、产品 UI 审计、技术决策（ADR）与全工程待办清单，统一见 [`docs/MASTER_REVIEW.md`](./MASTER_REVIEW.md)。

## 文档导航

| # | 文档 | 定位 |
|:---|:---|:---|
| 01 | [产品功能与UI/UX架构](./01.%20产品功能与UIUE架构.md) | 产品设计、页面布局、功能规划 |
| 02 | [Vibe Coding与AI工程规范](./02.%20Vibe%20Coding与AI工程规范.md) | 编码规范、测试标准、AI 代码生成指引 |
| 03 | [后端架构与执行引擎](./03.%20后端架构与执行引擎.md) | 后端架构、K线管道、认证、Hermes 集成 |
| 04 | [前端架构与零GC渲染](./04.%20前端架构与零GC渲染.md) | 前端架构、零GC数据流、渲染引擎选型 |
| 05 | [客户端架构（Flutter 三端）](./05.%20客户端架构与Tauri壳资源.md) | Android/iOS/HarmonyOS、APM、推送 |
| 06 | [工程化配置与部署方案](./06.%20工程化配置与部署方案.md) | 双 VPS + Cloudflare、CI/CD、Redis/pgvector |
| 07 | [子系统架构速查手册](./07.%20子系统架构速查手册.md) | 全局拓扑与各子系统快速参考 |
| 08 | [日志与可观测性规范](./08.%20日志与可观测性规范.md) | structlog 标准、Prometheus、Grafana |
| 09 | [性能测试规范](./09.%20性能测试规范.md) | SLO 目标、压测方案、CI 性能回归 |
| **10** | **[API 接口规范](./10.%20API接口规范.md)** | **REST/WS/SSE 完整契约、错误码表** |
| **11** | **[数据模型与领域设计](./11.%20数据模型与领域设计.md)** | **领域对象、DB Schema、Redis Key 规范** |
| **12** | **[运维手册与应急预案](./12.%20运维手册与应急预案.md)** | **Runbook、故障恢复、灾难恢复流程** |
| **13** | **[质量评估体系](./13.%20质量评估体系.md)** | **评分卡、定期 Review 流程、系统等级** |

### 子系统与专项架构（14~28）

> 01~13 是全局规范；本表是**单子系统**的实现架构（HOW）。按任务**单章**加载，禁止整本灌入（`AGENTS.md` §8）。
> 24~28 为「产品定义在 `docs/01 §二十五~§二十九` + 架构在本表」的配对文档。

| # | 文档 | 定位 | 状态 |
|:---|:---|:---|:---|
| 14 | [分布式数据源服务架构](./14.%20分布式数据源服务架构.md) | 数据源统一接口、运行模式、部署拓扑、热插拔 | 生效中 |
| 15 | [回测实盘同构引擎设计](./15.%20回测实盘同构引擎设计.md) | Algorithm/Engine 分离，对标 QuantConnect LEAN（BT-01） | 已落地 |
| 16 | [策略实验室完整架构](./16.%20策略实验室完整架构.md) | Monaco IDE + AI Diff + 沙箱隔离 + 版本存储（STRAT） | 已落地 |
| 17 | [纸面组合系统架构](./17.%20纸面组合系统架构.md) | 虚拟撮合 + 净值结算 + 绩效归档（PT） | 已落地 |
| 18 | [多通道推送路由设计](./18.%20多通道推送路由设计.md) | WS / 飞书 / Telegram，P0~P3 路由与冷却（ALERT-03） | 已落地 |
| 19 | [Parquet 数据湖快照版本化设计](./19.%20Parquet数据湖快照版本化设计.md) | 不可变快照，回测可复现的数据地基（DQ-03） | 已落地 |
| 20 | [前端视觉设计规范](./20.%20前端视觉设计规范.md) | design tokens、动效与视觉语言（FE-26） | 生效中 |
| 21 | [专家团多智能体协作系统](./21.%20专家团多智能体协作系统.md) | 多智能体辩论与角色编排 | Phase 1/3 |
| 22 | [Agent 工具链稳定性保障体系](./22.%20Agent%20工具链稳定性保障体系.md) | Tool 熔断、健康度与降级策略 | 生效中 |
| 23 | [业务数据源聚合 Facade 设计](./23.%20业务数据源聚合Facade设计.md) | 三层边界与红线收口（**§八 为现状 SSOT**） | 已落地 |
| 24 | [因子研究平台架构设计](./24.%20因子研究平台架构设计.md) | IC / 分层验证，对标 Alphalens（`FACT-01~05`） | 规划 |
| 25 | [执行质量分析架构设计](./25.%20执行质量分析架构设计.md) | 三层账本对齐与滑点归因（`TCA-01~04`） | 规划 |
| 26 | [事件驱动研究架构设计](./26.%20事件驱动研究架构设计.md) | 事件窗口 / PEAD 研究（`EVT-01~04`） | 规划 |
| 27 | [组合风险模型架构设计](./27.%20组合风险模型架构设计.md) | 因子协方差 + 风险分解 + Black-Litterman（`RMOD-01~04`） | 规划 |
| 28 | [公司财报看板架构设计](./28.%20公司财报看板架构设计.md) | 一手申报事实层 + 双时间轴 + 同业对比（`FIN-01~08`） | 规划 |

### 研究 / 待办专项文档

| 文档 | 定位 |
|:---|:---|
| [散户情绪数据源调研 TODO](./TODO-SENTIMENT-DATASOURCE.md) | 散户情绪数据源选型（Finnhub/StockGeist 否决，ApeWisdom 热度榜可落地） |
| [Futu 基本面/选股接口评估 TODO](./TODO-FUTU-FUNDAMENTAL-SCREEN.md) | 财务三大表为真增量，选股已覆盖 |
| [Futu 组合期权/新马日市场评估 TODO](./TODO-FUTU-OPTION-COMBO-MARKETS.md) | 组合期权行情 P0、交易预留、新马日暂缓 |
| [Futu 预测市场（事件合约）评估 TODO](./TODO-FUTU-EVENT-CONTRACT.md) | 隐含概率数据源，行情侧完整、交易侧缺失 |
| [Futu 行情搜索/FedWatch/基本面评估 TODO](./TODO-FUTU-SEARCH-MACRO.md) | 行情搜索+FedWatch 为真增量，指标列表/榜单/产业链跳过 |

## 1. 总体目录结构

以下是项目的基础目录结构：

    project-root/
    ├── AGENTS.md        # 跨 IDE 编码宪法（Cursor/Claude Code/Codex）
    ├── prompts/system/HERMES.md  # 盘中 Hermes 主脑运行时指令
    ├── backend/         # FastAPI 提供的前后端通信 API 接口与 WebSocket 服务
    ├── frontend/        # React + Vite 前端可视化交互与控制面板
    ├── hermes_agent/    # 底层大语言模型 Agent 引擎框架（负责 ReAct 推理循环）
    ├── tools/           # 量化专属 Tools 集合（行情、财报、交易、通知等核心外挂工具）
    ├── reports/         # 财报及研报 PDF 存放目录（供文档解析使用）
    ├── docs/            # 系统文档目录
    ├── main.py          # Quant Agent 主程序/终端入口，装载 Tools 并启动引擎
    ├── start.sh         # 本地一键启动脚本 (启动 FastAPI 与 Vite)
    ├── deploy.sh        # 一键容器化部署脚本 (支持远端增量部署)
    ├── docker-compose.yml # 容器编排文件
    ├── Dockerfile       # 项目 Docker 镜像构建描述（多阶段构建 Node + Python）
    └── requirements.txt # Python 依赖列表

## 2. 系统全局架构图 (System Architecture)

本项目采取了极度解耦的节点化设计，支持单机部署与微服务化演进。其全局物理拓扑与数据流向如下：

```mermaid
graph TD
    %% 客户端层
    subgraph Clients ["📱 多端指挥台 (Clients)"]
        A1[Web Frontend<br/>React / Vite / Tailwind]
        A2[iOS App<br/>Flutter / Impeller]
        A3[Android App<br/>Flutter / Impeller]
        A4[HarmonyOS<br/>Flutter / HMS Kit]
    end

    %% 网关层
    subgraph Gateway ["🚪 流量基座 (API Gateway Node)"]
        B1[WebSocket / SSE<br/>高频推送与大模型流]
        B2[RESTful API<br/>低频控制与状态查询]
    end

    %% AI 核心层
    subgraph AI_Brain ["🧠 AI 投研大脑 (Hermes Agent)"]
        C1[ReAct 推理引擎<br/>LangChain / Hermes]
        C2[量化工具外挂<br/>Tools Registry]
    end

    %% 高频数据与执行层
    subgraph Core_Engine ["⚙️ 数据与执行中枢 (Data & OMS Node)"]
        D1[Data Node<br/>行情清洗与防频控]
        D2[OMS Node<br/>风控与订单状态机]
    end

    %% 存储层
    subgraph Storage ["💽 混合存储基建 (Hybrid Storage)"]
        E1[(Redis)<br/>PubSub / Streams / Hash]
        E2[(PostgreSQL)<br/>PGVector / 强事务 ACID]
        E3[(DuckDB / Parquet)<br/>数据湖 / OLAP 回测]
    end

    %% 外部依赖层
    subgraph External ["🌐 外部数据与环境 (External)"]
        F1[Futu OpenD<br/>券商行情与交易 API]
        F2[YFinance / Finnhub<br/>三方补充数据源]
        F3[OpenAI / 本地 Ollama<br/>LLM 大模型推理]
    end

    %% 关系连线
    A1 <-->|WS / SSE| B1
    A1 <-->|HTTP| B2
    A2 & A3 & A4 <-->|WS / SSE| B1
    A2 & A3 & A4 <-->|HTTP| B2

    B1 <..>|Pub/Sub 极速派发| E1
    B2 <-->|CRUD 状态查询| E2
    B2 <-->|内网 HTTP 代理| C1

    C1 -->|SSE 思维链推送| B1
    C1 <-->|向量检索 RAG| E2
    C1 <-->|外部 LLM 调用| F3
    C1 -->|装载并调用| C2
    C2 -->|调用系统内部 API| B2

    D1 -->|清洗后推入总线| E1
    D1 <-->|拉取与容灾降级| F2
    D1 <-->|TCP 长连接| F1
    D2 <-->|ZeroMQ 微秒级通信| D1
    D2 <-->|事务读写| E2
    D2 <-->|交易发单与撤单| F1
```

## 3. 核心模块说明

为了降低系统的耦合度，本项目采用前后端分离的架构：

* **智能中枢 (Quant Agent)**: 核心决策系统，由 `hermes_agent` 和 `tools` 组成，根据 `AGENTS.md` 设定的架构约束，通过 `main.py` 执行量化策略、数据提纯和实盘监控。
* **API 网关 (Backend)**: 基于 FastAPI (`backend/main.py`)，提供多标的行情 WebSocket 推送及各类 API 接口，其内部拆分为 `core`, `routers`, `workers` 等细分模块来处理业务。
* **可视化面板 (Frontend)**: 基于 React 构建的前端系统，通过 WebSocket 接收实时推送并展示量化数据和监控画面。

## 4. 开发环境与规范

* **隔离原则**: 严格遵循 Clean Architecture，数据获取（Gateway）、逻辑推理（Agentic Layer）与交易执行（Tools Layer）物理隔离。
* **运行模式**: 默认沙箱（模拟盘）运行（`REAL_TRADE_EXECUTE=false`），受 Docker 资源约束 (512MB RAM)。
* **技术栈**: Python 3.11 (Backend & Agent), Node 20 (Frontend), Docker Compose (Deployment)。

## 5. 系统安装与运行指南

系统运行分为**本地开发环境**与**生产部署环境**，请根据需求选择启动方式。

### 5.1 开发环境 (Development)
开发环境支持前后端代码的热更新（Hot-Reload），适合日常编码和策略调试。
1. **环境准备**: 确保本地已安装 Python 3.11+ 和 Node.js 20+。
2. **依赖安装**:
   ```bash
   pip install -r requirements.txt   # 或 uv sync
   cd frontend && pnpm install && cd ..
   ```
3. **配置变量**: 复制 `.env.example` 为 `.env` 并填写 API Key 及相关配置。
4. **一键启动**:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```
   *注：后端 API 将运行在 8000 端口，前端 Vite 服务运行在 5173 端口。*

### 5.2 生产环境 (Production)
生产环境必须关闭代码热更新，前端需预先编译为静态文件由 FastAPI 代理，并通过 Docker 进行资源隔离。
1. **一键部署**:
   ```bash
   chmod +x prod_start.sh
   ./prod_start.sh
   ```
2. **手动部署流程**:
   * 编译前端资源: `cd frontend && pnpm install && pnpm build`
   * 启动生产容器: `docker-compose up -d --build`
   *注：生产环境统一收口于 8000 端口，请访问 `http://localhost:8000/monitor` 查看前端面板。*
