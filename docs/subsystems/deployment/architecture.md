# 部署子系统架构文档

> 最后更新：2026-06-27 | 版本：V2.0  
> 详细规范见 `docs/06. 工程化配置与部署方案.md`

## 一、节点拓扑（双 VPS + Cloudflare 边缘）

```
Cloudflare 边缘（免费）
  ├── Pages        → 前端 SPA 全球 CDN
  ├── Tunnel       → 零信任接入（替代暴露公网端口）
  ├── R2           → 报告/回测/备份对象存储
  ├── Workers      → 宏观数据边缘缓存
  └── Access       → Grafana/Prometheus 管理页鉴权

节点 A：香港 VPS（执行核心）          节点 B：境外 VPS（AI + 监控）
  Futu OpenD（systemd 守护）            Hermes Agent + Ollama LLM
  quant-worker（行情抓取）              Prometheus + Grafana
  Redis 主节点（AOF + RDB）             Redis 从节点（可选，读扩展）
  FastAPI API 网关                      DuckDB 离线回测工作台
  PostgreSQL + pgvector
  Nginx（Cloudflare Tunnel 下可省）
```

## 二、部署模式总览

| 模式 | 适用场景 | 命令 | 特点 |
|:---|:---|:---|:---|
| **本地开发** | 日常编码调试 | `./start.sh` | 热更新，无 Docker |
| **节点 A 生产** | 香港 VPS 全栈部署 | `docker-compose up -d` | ghcr.io 拉取镜像 |
| **节点 B AI** | 境外 VPS AI + 监控 | `docker-compose -f docker-compose.node-b.yml up -d` | 轻量服务 |
| **前端 CDN** | GitHub Actions 自动触发 | `wrangler pages deploy` | Cloudflare Pages |

## 三、Docker Compose 服务矩阵（节点 A）

| 服务 | 镜像 | 端口（仅内网） | 职责 |
|:---|:---|:---|:---|
| `quant-agent` | `ghcr.io/*/quant_agent:latest` | 8000 | FastAPI 网关 |
| `redis` | `redis:7-alpine` | 6379 | 行情缓存 + Pub/Sub |
| `postgres` | `pgvector/pgvector:pg16` | 5432 | 数据持久化 + 向量库 |
| `nginx` | `nginx:alpine` | 80, 443 | SSL 终止（Tunnel 模式下可省）|
| `prometheus` | `prom/prometheus` | 9090 | 指标采集 |
| `grafana` | `grafana/grafana` | 3000 | 监控面板（CF Access 保护） |

## 四、Redis Key 命名规范（快速参考）

```
quote:tick:{symbol}          最新 Tick 快照（TTL 30s）
quote:kline:{period}:{symbol} K线列表（最新 100 根）
screener:result:{query_hash} 选股结果（TTL 5min）
macro:assets                 宏观资产跑马灯（TTL 2min）
session:{user_id}            用户会话（JWT 黑名单）
stale:{original_key}        降级数据（原缓存过期后的备份）
```

## 五、pgvector 运维速查

| 操作 | 命令 |
|:---|:---|
| 导出向量库 | `pg_dump -t knowledge_chunks -F c -f dump.pgdump` |
| 上传至 R2 | `aws s3 cp dump.pgdump s3://quant-backups/pgvector/ --endpoint-url ...` |
| 恢复向量库 | `pg_restore -d quant_agent_db dump.pgdump` |
| 重建向量索引 | `REINDEX INDEX CONCURRENTLY idx_knowledge_embedding` |
| 清理过期向量 | `DELETE FROM knowledge_chunks WHERE expires_at < NOW()` |

## 六、Cloudflare 免费资源使用清单

| 产品 | 用途 | 免费额度 |
|:---|:---|:---|
| Pages | 前端 SPA 全球 CDN | 无限请求 |
| Tunnel | 安全接入（替代暴露端口）| 免费 |
| R2 | 报告/回测/备份存储 | 10GB/月 |
| Workers | 边缘 API 缓存代理 | 10万次/日 |
| Access | 管理页面零信任鉴权 | 免费（50用户以内）|
| WAF & DDoS | 攻击防护 | 免费基础版 |

## 七、月度费用

| 资源 | 费用 |
|:---|:---|
| 香港 VPS（腾讯云轻量 2C/4G）| ¥24 |
| 境外 VPS（Hetzner CX22）| ≈ ¥31 |
| Cloudflare 全套 | ¥0 |
| GitHub Actions / ghcr.io | ¥0 |
| **合计** | **≈ ¥55/月** |

## 八、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-27 V2.0 | 更新为双节点拓扑 + Cloudflare 免费资源体系 |
| 2026-06-27 V1.0 | 初始版本 |

## 一、部署模式总览

| 模式 | 适用场景 | 命令 | 特点 |
|:---|:---|:---|:---|
| **本地开发** | 日常编码、调试 | `./start.sh` | 热更新，无 Docker |
| **单机生产** | VPS 单节点部署 | `docker-compose up -d` | 全栈容器化 |
| **分布式** | 多 VPS + 境外 Worker | `docker-compose up -d quant-worker`（Worker 节点） | 数据抓取与 Web 分离 |

## 二、Docker Compose 服务矩阵

```yaml
# docker-compose.yml 服务定义（概览）
services:
  quant-agent:          # FastAPI 后端 + Hermes Agent
    ports: [8000]
    healthcheck: GET /health
    depends_on: [redis, postgres]

  redis:                # 行情总线 + 状态缓存
    image: redis:7-alpine
    volumes: [./data/redis:/data]  # AOF 持久化
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}

  postgres:             # 订单/持仓/策略/向量 RAG
    image: pgvector/pgvector:pg16
    volumes: [./data/postgres:/var/lib/postgresql/data]
    healthcheck: pg_isready

  prometheus:           # 指标采集
    ports: [9090]
    volumes: [./prometheus.yml:/etc/prometheus/prometheus.yml]

  grafana:              # 监控看板
    ports: [3000]
    volumes: [./grafana:/etc/grafana/provisioning]
```

## 三、环境变量清单

```bash
# .env.example — 所有必需配置项
# === LLM ===
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini            # 工具调用模型
OPENAI_MODEL_HEAVY=gpt-4o           # 深度分析模型
OLLAMA_BASE_URL=http://localhost:11434  # 本地降级

# === 数据源 ===
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FINNHUB_API_KEY=...
FRED_API_KEY=...

# === 存储 ===
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_strong_password
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/quant_db

# === 安全 ===
REAL_TRADE_EXECUTE=false             # 实盘开关，默认关闭
SECRET_KEY=random_32_char_string     # JWT 签名密钥
ALLOWED_ORIGINS=http://localhost:5173,https://your-domain.com

# === 通知 ===
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# === 运行模式 ===
DEBUG=false
LOG_LEVEL=INFO
```

## 四、分布式部署网络拓扑

```
┌──────────────────────────────────────────────────────────┐
│  主服务器（境内 VPS / 本地机）                             │
│  运行：FastAPI + Redis + PostgreSQL + Grafana             │
│  对外：80/443（Nginx 反代）                               │
│  内网：6379（Redis）/ 5432（PG）仅对 Worker 节点白名单    │
└────────────────────────┬─────────────────────────────────┘
                         │ Redis Pub/Sub（公网加密）
┌────────────────────────▼─────────────────────────────────┐
│  Worker 节点（境外 VPS — 低延迟接入海外数据源）            │
│  运行：quant-worker 容器（仅数据抓取）                    │
│  环境：REDIS_HOST = 主服务器公网 IP                       │
│         DATABASE_URL = 主服务器公网 PG                    │
│  启动：docker-compose up -d quant-worker                  │
└──────────────────────────────────────────────────────────┘
```

## 五、安全加固清单

```bash
# SSH 加固
PasswordAuthentication no          # 禁用密码登录
Port 22022                         # 修改默认端口

# UFW 防火墙（主服务器）
ufw allow 22022/tcp                # SSH
ufw allow 80,443/tcp               # HTTP/HTTPS
ufw allow from <Worker IP> to any port 6379  # Redis 白名单
ufw allow from <Worker IP> to any port 5432  # PG 白名单
ufw enable

# Docker 网络（不暴露 Redis/PG 到 0.0.0.0）
# 使用 Docker 内部网络通信，只有 FastAPI 端口对外
```

## 六、国内 VPS 特殊配置

```dockerfile
# Dockerfile 中切换镜像源（国内节点构建时）
RUN pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ -r requirements.txt

# npm 镜像（前端构建时）
RUN npm config set registry https://registry.npmmirror.com
```

```bash
# 访问 OpenAI API 代理（国内节点）
OPENAI_BASE_URL=https://your-proxy.com/v1  # 可选代理地址
```

## 七、CI/CD 流程

```
代码推送到 main 分支
    ↓
GitHub Actions 触发
    ↓ (并行)
    ├── Python Lint (ruff) + 单元测试 + 覆盖率检查
    └── Frontend Lint + TypeScript 检查 + Vitest + 构建验证
    ↓ (全部通过)
构建 Docker 镜像 → GHCR (ghcr.io/user/quant-agent:v2026.06.27-{sha})
    ↓
SSH 连接至 VPS
    ↓
docker-compose pull → docker-compose up -d --no-deps quant-agent
    ↓
健康检查 GET /health（等待 30s，失败则回滚）
    ↓
Telegram 通知部署结果
```

## 八、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-27 | 初始版本，覆盖三种部署模式、安全加固、CI/CD 流程 |
