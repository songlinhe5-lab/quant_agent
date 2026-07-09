# 部署子系统架构文档

> 最后更新：2026-07-08 | 版本：V4.0  
> 详细规范见 `docs/06. 工程化配置与部署方案.md`

## 一、节点拓扑（单一海外 VPS + Cloudflare 边缘）

```
Cloudflare 边缘（免费）
  ├── Pages        → 前端 SPA 全球 CDN
  ├── R2           → 报告/回测/备份对象存储
  ├── Workers      → 宏观数据边缘缓存
  └── Access       → Grafana/Prometheus 管理页鉴权

海外 VPS（单一节点）
  FastAPI 主服务 API（对外）
  Worker（采集器 daemon + 后台任务）
  Redis（行情缓存）
  PostgreSQL + pgvector
  Prometheus + Grafana 监控（可选）
  Futu OpenD（宿主机本地运行，容器通过 host-gateway 访问）
```

## 二、部署模式总览

| 模式 | 适用场景 | 命令 | 特点 |
|:---|:---|:---|:---|
| **本地开发** | 日常编码调试 | `./start.sh` | 热更新，无 Docker |
| **生产部署** | 单一 VPS | `docker compose up -d` | 本地构建镜像 |
| **前端 CDN** | GitHub Actions 自动触发 | `wrangler pages deploy` | Cloudflare Pages |

## 三、Docker Compose 服务矩阵

| 服务 | 镜像 | 端口（仅内网） | 职责 |
|:---|:---|:---|:---|
| `quant-agent` | 本地构建 | 8000 | FastAPI 主服务 API |
| `quant-worker` | 本地构建 | - | Worker 进程（采集器 daemon + 后台任务） |
| `redis` | `redis:7-alpine` | 6379 | 行情缓存 |
| `postgres` | `pgvector/pgvector:pg15` | 5432 | 数据持久化 + 向量库 |
| `prometheus` | `prom/prometheus` | 9090 | 指标采集（monitoring profile） |
| `grafana` | `grafana/grafana` | 3001 | 监控面板（monitoring profile） |

## 四、Redis Key 命名规范（快速参考）

```
quote:tick:{symbol}          最新 Tick 快照（TTL 30s）
quote:kline:{period}:{symbol} K线列表（最新 100 根）
screener:result:{query_hash} 选股结果（TTL 5min）
macro:assets                 宏观资产跑马灯（TTL 2min）
session:{user_id}            用户会话（JWT 黑名单）
stale:{original_key}        降级数据（原缓存过期后的备份）
quant:cache:{action}:{ticker} 采集结果缓存（TTL 5min）
```

## 五、pgvector 运维速查

| 操作 | 命令 |
|:---|:---|
| 导出向量库 | `pg_dump -t knowledge_chunks -F c -f dump.pgdump` |
| 恢复向量库 | `pg_restore -d quant_agent_db dump.pgdump` |
| 重建向量索引 | `REINDEX INDEX CONCURRENTLY idx_knowledge_embedding` |
| 清理过期向量 | `DELETE FROM knowledge_chunks WHERE expires_at < NOW()` |

## 六、Cloudflare 免费资源使用清单

| 产品 | 用途 | 免费额度 |
|:---|:---|:---|
| Pages | 前端 SPA 全球 CDN | 无限请求 |
| R2 | 报告/回测/备份存储 | 10GB/月 |
| Workers | 边缘 API 缓存代理 | 10万次/日 |
| Access | 管理页面零信任鉴权 | 免费（50用户以内）|
| WAF & DDoS | 攻击防护 | 免费基础版 |

## 七、月度费用

| 资源 | 费用 |
|:---|:---|
| 海外 VPS（4C/4G/80G SSD） | $10-15 ≈ ¥70-105 |
| Cloudflare 全套 | ¥0 |
| GitHub Actions / ghcr.io | ¥0 |
| **合计** | **≈ ¥70-105/月** |

## 八、环境变量配置

```bash
# === .env ===
# 采集器
COLLECTOR_FUTU=true
COLLECTOR_YFINANCE=true
COLLECTOR_FINNHUB=false
COLLECTOR_AKSHARE=false

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_strong_password

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/quant_agent_db

# Futu OpenD (宿主机本地运行)
FUTU_HOST=127.0.0.1
FUTU_PORT=11111

# 其他
REAL_TRADE_EXECUTE=false
SECRET_KEY=your_jwt_secret
OPENAI_API_KEY=your_openai_key
```

## 九、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-07-08 V4.0 | 架构简化：移除主从集群，改为单一海外 VPS 部署；所有数据源本地化采集；清理重复内容 |
| 2026-06-28 V3.1 | 安全接入方案从 Cloudflare Tunnel 替换为 Tailscale |
| 2026-06-28 V3.0 | 架构重构：北京主节点 + 加州数据子节点，服务注册表，动态路由，移除 Nginx |
| 2026-06-27 V2.0 | 更新为双节点拓扑 + Cloudflare 免费资源体系 |
| 2026-06-27 V1.0 | 初始版本 |
