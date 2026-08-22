---
kind: dependency_management
name: 多语言多模块依赖管理：uv + pnpm + Flutter pub 三套工具与可选依赖隔离
category: dependency_management
scope:
    - '**'
source_files:
    - pyproject.toml
    - uv.lock
    - backend/requirements.txt
    - data_subservice/requirements.txt
    - data_subservice/Dockerfile
    - frontend/package.json
    - frontend/pnpm-lock.yaml
    - client/flutter_app/pubspec.yaml
    - client/flutter_app/pubspec.lock
---

## 1. 使用的系统/工具

仓库是一个多语言、多进程工程，Python（后端主服务 + data_subservice）、前端（Vite+React）、Flutter 客户端各自使用独立的包管理器：
- Python：**uv**（`pyproject.toml` + `uv.lock`）作为唯一权威依赖声明与锁定文件；同时保留 `backend/requirements.txt`、`data_subservice/requirements.txt` 作为「可读性收口清单」和开发/调试参考。
- 前端：pnpm（`frontend/package.json` + `frontend/pnpm-lock.yaml`），lockfileVersion 9.0。
- Flutter：pub（`client/flutter_app/pubspec.yaml` + `client/flutter_app/pubspec.lock`），SDK 约束 `^3.12.2`。

构建镜像通过 Dockerfile 调用 `uv sync --no-dev --extra datasource-all` 安装依赖，并使用阿里云 PyPI 镜像（`PIP_INDEX_URL` / `UV_INDEX_URL` = `https://mirrors.aliyun.com/pypi/simple/`）加速下载。

## 2. 关键文件
- `pyproject.toml`：定义项目名、`requires-python >= 3.11`、生产依赖、`[project.optional-dependencies]`（`datasource-all`、`local-embedding`、已废弃兼容的 `dev`）、`[dependency-groups].dev`（ruff==0.15.16、mypy、pre-commit、pytest-* 等开发工具链），以及 ruff、pytest、coverage 配置。
- `uv.lock`：由 uv 生成的完整解析锁文件，包含所有依赖的 sha256、wheel URL、平台 marker 矩阵。
- `backend/requirements.txt`：仅声明主服务运行所需的核心库（fastapi、pandas、numpy、httpx、redis 等），注释明确禁止在主服务直连任何第三方数据源 SDK。
- `data_subservice/requirements.txt`：全量 SDK 清单（futu-api、tushare、akshare、yfinance、protobuf 等），注释强调「NOT 用于生产镜像构建」，生产镜像走 pyproject extra。
- `data_subservice/Dockerfile`：基于 python:3.11-slim 的多阶段构建，设置 `DS_EXTRA=datasource-all`，通过 `uv sync --extra ${DS_EXTRA}` 安装，运行时用 `DS_CAPABILITIES` 环境变量按节点能力隔离。
- `frontend/package.json` + `frontend/pnpm-lock.yaml`：声明 React 18、Radix UI、ag-grid、echarts、monaco-editor、zustand 等依赖及 devDependencies。
- `client/flutter_app/pubspec.yaml` + `pubspec.lock`：声明 dio、go_router、flutter_riverpod、web_socket_channel、flutter_secure_storage 等。

## 3. 架构与约定
- **主服务与数据源物理隔离**：`backend/requirements.txt` 的注释是「架构红线」——主服务只能通过 DataSourceRouter 经 HTTP 调用远程 data_subservice，禁止在主环境 import futu-api/tushare/akshare/yfinance。数据源 SDK 全部集中在 `data_subservice`，并通过 `pyproject.toml` 的 `optional-dependencies.datasource-all` 以 extra 形式按需安装。
- **可选依赖分组**：`datasource-all` 聚合 yfinance、tushare、akshare、futu-api、finnhub-python；`local-embedding` 提供本地 sentence-transformers；`dev` extra 仅为兼容历史命令保留，新工具应放入 `[dependency-groups].dev`。
- **可复现构建**：生产镜像使用 `uv.lock` 锁定版本；开发工具链中 ruff 锁定到 `==0.15.16`，mypy 限制 `<3` 防止破坏性变更导致校验漂移。
- **镜像体积控制**：Dockerfile 注释说明合并为单一 `data-subservice` 镜像（而非按地域拆分），通过运行时 `DS_CAPABILITIES` 返回 503 屏蔽未声明能力，实测各镜像尺寸差异仅 2~4%。
- **缓存清理**：构建后删除 `.venv` 中的 `__pycache__`、`*.pyc`、`*.egg-info`、`tests` 目录以缩小镜像。

## 4. 约定与约束
- **版本策略**：`requirements.txt` 统一采用 `>=X.Y.Z` 取下限不锁死，注释建议「如需可复现构建请改用 requirements.lock / poetry.lock」；实际可复现由 `uv.lock` 承担。
- **禁止主服务直连数据源 SDK**：`backend/requirements.txt` 注释明文规定「⚠️ 架构红线：主服务仅经 DataSourceRouter 走 HTTP 调用远程数据源子服务，禁止在主服务内直连任何第三方数据源 SDK」。
- **data_subservice 依赖仅限调试**：`data_subservice/requirements.txt` 注释警告「本文件为「全量 SDK 清单」，仅用于本地开发/调试参考，NOT 用于生产镜像构建」，误用 `pip install -r` 会使镜像从 ~400MB 飙到 500MB+。
- **PyPI 镜像**：Dockerfile 显式设置 `PIP_INDEX_URL` 与 `UV_INDEX_URL` 指向阿里云镜像，并设置 `UV_HTTP_TIMEOUT=300`。
- **测试隔离**：`pyproject.toml` 的 pytest 配置将 testpaths 限定为 `backend/tests`，避免 collection 阶段 import data_subservice 的重型 SDK 失败拖垮整轮。
- **覆盖率门槛**：`fail_under = 80`，并通过 `omit` 排除外部数据源封装、scheduler 入口、生命周期代码等低价值单测区域。
- **Flutter SDK 约束**：`environment.sdk: ^3.12.2`，依赖均使用 `^` 语义化版本范围，`pubspec.lock` 锁定具体解析结果。
- **前端依赖**：pnpm lockfileVersion 9.0，所有依赖在 `package.json` 中以 `^` 指定范围，`pnpm-lock.yaml` 记录精确解析版本与 peer 依赖关系。
