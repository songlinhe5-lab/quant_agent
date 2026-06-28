# 部署子系统架构文档

> 最后更新：2026-06-28 | 版本：V3.1  
> 详细规范见 `docs/06. 工程化配置与部署方案.md`

## 一、节点拓扑（北京主节点 + 加州数据子节点 + Cloudflare 边缘）

```
Cloudflare 边缘（免费）
  ├── Pages        → 前端 SPA 全球 CDN
  ├── Tailscale    → 跨节点内网穿透 + SSH 安全接入
  ├── R2           → 报告/回测/备份对象存储
  ├── Workers      → 宏观数据边缘缓存
  └── Access       → Grafana/Prometheus 管理页鉴权

节点 A：北京 VPS（主力 4C4G）           节点 B：加州 VPS（数据子服务）
  FastAPI 主服务 API（对外）              数据子服务 API
  服务注册表 (Redis/内存)                 yfinance（美股/全球行情）
  akshare 数据采集（直连国内）            finnhub（全球新闻/基本面）
  Redis（行情缓存 + 注册中心）              futuopenai（港美股交易网关）
  PostgreSQL + pgvector
  Prometheus + Grafana 监控
  Hermes Agent + LLM（可选）            启动时向北京主服务注册 IP:Port
```

## 二、部署模式总览

| 模式 | 适用场景 | 命令 | 特点 |
|:---|:---|:---|:---|
| **本地开发** | 日常编码调试 | `./start.sh` | 热更新，无 Docker |
| **北京节点生产** | 主服务部署 | `docker-compose up -d` | ghcr.io 拉取镜像 |
| **加州节点生产** | 数据子服务 | `docker-compose -f docker-compose.node-b.yml up -d` | 轻量服务 |
| **前端 CDN** | GitHub Actions 自动触发 | `wrangler pages deploy` | Cloudflare Pages |

## 三、Docker Compose 服务矩阵

### 北京节点

| 服务 | 镜像 | 端口（仅内网） | 职责 |
|:---|:---|:---|:---|
| `quant-agent` | `ghcr.io/*/quant_agent:latest` | 8000 | FastAPI 主服务 API |
| `redis` | `redis:7-alpine` | 6379 | 行情缓存 + 注册中心 + Pub/Sub |
| `postgres` | `pgvector/pgvector:pg16` | 5432 | 数据持久化 + 向量库 |
| `prometheus` | `prom/prometheus` | 9090 | 指标采集 |
| `grafana` | `grafana/grafana` | 3000 | 监控面板（CF Access 保护） |

### 加州节点

| 服务 | 镜像 | 端口（仅内网） | 职责 |
|:---|:---|:---|:---|
| `data-subservice` | `ghcr.io/*/data-subservice:latest` | 8100 | 海外数据源采集 API |

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
| Tailscale | 跨节点内网穿透 + SSH | 免费（≤100 设备） |
| R2 | 报告/回测/备份存储 | 10GB/月 |
| Workers | 边缘 API 缓存代理 | 10万次/日 |
| Access | 管理页面零信任鉴权 | 免费（50用户以内）|
| WAF & DDoS | 攻击防护 | 免费基础版 |

## 七、月度费用

| 资源 | 费用 |
|:---|:---|
| 北京 VPS（腾讯/阿里云 4C/4G）| ¥40-60 |
| 加州 VPS（BandwagonHost/Vultr 2C/2G）| ≈ ¥35-70 |
| Cloudflare 全套 | ¥0 |
| GitHub Actions / ghcr.io | ¥0 |
| **合计** | **≈ ¥75-130/月** |

## 八、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-28 V3.1 | 安全接入方案从 Cloudflare Tunnel 替换为 Tailscale |
| 2026-06-28 V3.0 | 架构重构：北京主节点 + 加州数据子节点，服务注册表，动态路由，移除 Nginx |
| 2026-06-27 V2.0 | 更新为双节点拓扑 + Cloudflare 免费资源体系 |
| 2026-06-27 V1.0 | 初始版本 |

---

## 补充说明

### 环境变量清单

```bash
# === 北京节点 .env ===
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_MODEL_HEAVY=gpt-4o
OLLAMA_BASE_URL=http://localhost:11434
AKSHARE_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_strong_password
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/quant_db
REAL_TRADE_EXECUTE=false
SECRET_KEY=random_32_char_string
ALLOWED_ORIGINS=http://localhost:5173,https://your-domain.com
HMAC_SECRET=internal_hmac_secret
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DEBUG=false
LOG_LEVEL=INFO
```

```bash
# === 加州节点 .env.node-b ===
MAIN_SERVICE_URL=https://internal.yourdomain.com
NODE_ID=california-01
HMAC_SECRET=internal_hmac_secret
FINNHUB_API_KEY=...
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_TRADE_PASSWORD=...
```

### 国内 VPS 特殊配置

```dockerfile
# Dockerfile 中切换镜像源（北京节点构建时）
RUN pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ -r requirements.txt
RUN npm config set registry https://registry.npmmirror.com
```

```bash
# 访问 OpenAI API 代理（北京节点）
OPENAI_BASE_URL=https://your-proxy.com/v1
```
