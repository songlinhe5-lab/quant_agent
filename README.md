# Quant Agent

AI 驱动的极客量化交易终端

[![Backend CI](https://github.com/your-username/quant_agent/actions/workflows/backend.yml/badge.svg)](https://github.com/your-username/quant_agent/actions/workflows/backend.yml)
[![Frontend CI](https://github.com/your-username/quant_agent/actions/workflows/frontend.yml/badge.svg)](https://github.com/your-username/quant_agent/actions/workflows/frontend.yml/badge.svg)
[![Security Scan](https://github.com/your-username/quant_agent/actions/workflows/security.yml/badge.svg)](https://github.com/your-username/quant_agent/actions/workflows/security.yml/badge.svg)

## 项目简介

Quant Agent 是一个现代化的量化交易终端，集成了 AI 智能分析、实时行情、策略回测、订单管理等功能。

### 核心特性

- 🤖 **AI 智能分析**: 基于 Hermes Agent 的智能化市场分析和策略建议
- 📊 **实时行情**: WebSocket 实时推送，支持 Level 2 盘口数据
- 🧪 **策略回测**: 集成 VectorBT 极速回测引擎
- 📈 **选股器**: 支持复杂横截面选股和 AI 驱动的选股建议
- 🔒 **安全优先**: HMAC 签名验证、审计日志、敏感数据加密
- ⚡ **高性能**: 零 GC 数据管道、Web Worker 计算、PixiJS WebGL 渲染

## 技术栈

### 后端
- **框架**: FastAPI
- **数据库**: PostgreSQL + pgvector
- **缓存**: Redis
- **ORM**: SQLAlchemy
- **认证**: JWT 双令牌体系

### 前端
- **框架**: React 18 + Vite
- **状态管理**: Zustand
- **UI 组件**: shadcn/ui + Tailwind CSS
- **图表**: Lightweight Charts + ECharts + PixiJS
- **路由**: React Router v6

## 快速开始

### 后端启动

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### 前端启动

```bash
cd frontend
pnpm install
pnpm dev
```

## 项目结构

```
quant_agent/
├── backend/              # 后端服务
│   ├── core/            # 核心模块（配置、安全、数据库）
│   ├── routers/         # API 路由
│   ├── services/        # 业务服务
│   └── tests/           # 单元测试
├── frontend/            # 前端应用
│   ├── src/
│   │   ├── components/  # UI 组件
│   │   ├── features/    # 功能模块
│   │   ├── services/    # API 服务
│   │   └── types/       # 类型定义
│   └── public/
├── docs/                # 文档
├── .github/             # GitHub Actions CI/CD
└── README.md
```

## CI/CD

本项目使用 GitHub Actions 进行持续集成和部署：

- **后端 CI**: 每次 push/PR 自动运行测试、lint、类型检查
- **前端 CI**: 每次 push/PR 自动运行测试、lint、构建
- **安全扫描**: 每周自动运行漏洞扫描

### Pre-commit Hooks

安装 pre-commit hooks 以在本地提交前运行测试：

```bash
pip install pre-commit
pre-commit install
```

## 文档

- [前端架构与零GC渲染](docs/04.%20前端架构与零GC渲染.md)
- [后端架构](docs/03.%20后端架构与核心设计.md)
- [前端目录结构规范](docs/前端目录结构规范.md)
- [TODO 追踪矩阵](docs/TODO.md)

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

提交前请确保：
1. 所有测试通过 (`pytest` / `pnpm run test`)
2. Lint 检查通过 (`ruff check` / `pnpm run lint`)
3. 提交信息符合 Conventional Commits 规范
