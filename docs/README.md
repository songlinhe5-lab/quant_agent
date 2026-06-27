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

## 1. 总体目录结构

以下是项目的基础目录结构：

    project-root/
    ├── AGENTS.md        # 主脑 Agent 系统指令与核心架构约束
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
