# 🔧 Quant Agent 多节点部署配置检查清单

## 📋 配置总览

| 配置项 | Master (国内) | Slave-1 (海外) | Slave-2~4 (海外) | 本地 .env |
|--------|---------------|----------------|------------------|-----------|
| **节点拓扑** |
| NODE_ROLE | master | slave | slave | - |
| COMPOSE_PROFILES | master,monitoring | slave | slave | - |
| SLAVE_ID | - | overseas-1 | overseas-2~4 | - |
| NODE_HOST | - | <Slave-1 IP> | <Slave-X IP> | - |
| NODE_PORT | - | 8001 | 8001 | - |
| MASTER_NODES | - | [{"id":"beijing","host":"120.53.84.116","port":6379,"password":"tradingagents123"}] | 同 Slave-1 | - |
| SLAVE_NODES | http://<S1>:8001,http://<S2>:8001,... | - | - | - |
| **数据源能力 (DS_CAPABILITIES)** |
| DS_CAPABILITIES | `futu,sentiment` | `yfinance` | `yfinance` | - |
| （CN-DATA 节点） | `akshare,tushare` | - | - | - |
| *sentiment 说明* | *ApeWisdom 散户社交媒体热度（免费无 Key、全球可访问），随主节点 S1 声明即可；未声明 `sentiment` 能力的节点调 `/api/v1/data?source=sentiment` 返回 503，主服务 `fetch_sentiment` 判该节点不健康→熔断。* | - | - | - |
| DATA_SOURCE_ROUTER_ENABLED | ✅ true | ✅ true | ✅ true | - |
| *说明* | *主服务数据源能力默认全开，不再用 `COLLECTOR_*` 开关门控；子服务仅响应 `DS_CAPABILITIES` 声明的能力（其余返回 503）；数据源失效统一在监控 (router.get_health_status) 显示，而非静默禁用。* |
| **基础设施** |
| REDIS_HOST | localhost | - | - | localhost |
| REDIS_PORT | 6379 | - | - | 6379 |
| REDIS_PASSWORD | tradingagents123 | - | - | tradingagents123 |
| **数据库** |
| DB_USER | quant_admin | - | - | quant_admin |
| DB_PASSWORD | quant_pg_secret_2026 | - | - | quant_pg_secret_2026 |
| DB_NAME | quant_agent_db | - | - | quant_agent_db |
| DATABASE_URL | postgresql://... | - | - | postgresql://... |
| EMBEDDING_DIM | 1024 | - | - | 1024 |
| MEILISEARCH_HOST | http://127.0.0.1:7700 | - | - | http://127.0.0.1:7700 |
| MEILISEARCH_API_KEY | <your_key> | - | - | <your_key> |
| **LLM & Embedding** |
| LLM_API_KEY | sk-acb4e3430fcc4c10b15d5649cdaf054e | - | - | sk-acb4e3430fcc4c10b15d5649cdaf054e |
| LLM_BASE_URL | https://api.deepseek.com | - | - | https://api.deepseek.com |
| LLM_MODEL | deepseek-v4-flash | - | - | deepseek-v4-flash |
| LLM_PRO_MODEL | deepseek-v4-pro | - | - | deepseek-v4-pro |
| EMBEDDING_API_KEY | sk-awakqrsllmdlgwlmliayrcxaqmwhshwvlfhshszqsgcwjtym | - | - | sk-awakqrsllmdlgwlmliayrcxaqmwhshwvlfhshszqsgcwjtym |
| EMBEDDING_BASE_URL | https://api.siliconflow.cn/v1 | - | - | https://api.siliconflow.cn/v1 |
| EMBEDDING_MODEL | BAAI/bge-large-zh-v1.5 | - | - | BAAI/bge-large-zh-v1.5 |
| **数据源 API Keys** |
| FMP_API_KEY | 6pSGyA3dspPsjz4NcWMPor0pfeingsTE | - | - | 6pSGyA3dspPsjz4NcWMPor0pfeingsTE |
| FINNHUB_API_KEY | d2coo7pr01qihtcsq7n0d2coo7pr01qihtcsq7ng | ✅ 同 Master | ❌ 不需要 | d2coo7pr01qihtcsq7n0d2coo7pr01qihtcsq7ng |
| AKSHARE_API_KEY | 9b53f8c411b5980f7f2384f722857a2e177f8561 | ❌ 不需要 | ❌ 不需要 | 9b53f8c411b5980f7f2384f722857a2e177f8561 |
| FRED_API_KEY | ff3cb5acfdf642751b1f1aa2d2c450c9 | ✅ 同 Master | ✅ 同 Master | ff3cb5acfdf642751b1f1aa2d2c450c9 |
| **Futu OpenD (仅 Slave-1)** |
| FUTU_HOST | - | 127.0.0.1 | - | 127.0.0.1 |
| FUTU_PORT | - | 11111 | - | 11111 |
| FUTU_TRD_ENV | - | SIMULATE | - | SIMULATE |
| FUTU_PWD_UNLOCK | - | (留空) | - | (留空) |
| **通知与告警** |
| FEISHU_WEBHOOK_URL | https://open.feishu.cn/... | - | - | https://open.feishu.cn/... |
| SERVERCHAN_SENDKEY | SCT355206TnmTEBt52Wucy6fkm3naW9lXM | - | - | SCT355206TnmTEBt52Wucy6fkm3naW9lXM |
| TELEGRAM_BOT_TOKEN | <your_token> | - | - | <your_token> |
| TELEGRAM_CHAT_ID | <your_chat_id> | - | - | <your_chat_id> |
| ALERT_WEBHOOK_URL | https://oapi.dingtalk.com/... | - | - | https://oapi.dingtalk.com/... |
| **搜索引擎 API** |
| GOOGLE_SEARCH_API_KEY | AIzaSyAWkdAuzHCN63J-8sA8HWrTkmCZz5ZfD0A | - | - | AIzaSyAWkdAuzHCN63J-8sA8HWrTkmCZz5ZfD0A |
| GOOGLE_SEARCH_CX | b55cf8e8acc394949 | - | - | b55cf8e8acc394949 |
| BING_SEARCH_API_KEY | <your_key> | - | - | <your_key> |
| TAVILY_API_KEY | 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 | - | - | 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 |
| BOCHA_API_KEY | sk-9e826741c3a740e486d7699e028eeee9 | - | - | sk-9e826741c3a740e486d7699e028eeee9 |
| **OAuth** |
| GOOGLE_CLIENT_ID | 232922208480-... | - | - | 232922208480-... |
| GOOGLE_CLIENT_SECRET | GOCSPX-... | - | - | GOCSPX-... |
| **🔐 安全与加密 (所有节点必须一致)** |
| INTERNAL_API_SECRET | <生成> | <同 Master> | <同 Master> | <生成> |
| ENCRYPTION_MASTER_KEY | <生成> | <同 Master> | <同 Master> | <生成> |
| **全局风控** |
| QUANT_ENV | development | production | production | development |
| BACKEND_API_URL | http://127.0.0.1:8000/api | - | - | http://127.0.0.1:8000/api |
| REAL_TRADE_EXECUTE | false | false | false | false |
| **OpenTelemetry (可选)** |
| OTEL_ENABLED | true | - | - | true |
| OTEL_SERVICE_NAME | quant-agent | - | - | quant-agent |
| OTEL_EXPORTER_OTLP_ENDPOINT | http://localhost:4318/v1/traces | - | - | http://localhost:4318/v1/traces |
| OTEL_SAMPLING_RATE | 1.0 | - | - | 1.0 |
| **CORS (可选)** |
| ALLOWED_ORIGINS | https://your-domain.pages.dev,... | - | - | https://your-domain.pages.dev,... |
| **前端 Cloudflare Pages 构建变量** |
| VITE_API_BASE_URL | https://quant-api.stephenhe.com/api/v1 | - | - | https://quant-api.stephenhe.com/api/v1 |

> ⚠️ **VITE_API_BASE_URL 红线**：必须指向 **`quant-api` 子域**（独立 API 域名），**绝不能**写成 `quant.stephenhe.com`（漏 `api-`）。两者 cross-site，错配会导致：① 大盘面板空白（REST 打到被 Cloudflare 拦截的域名）② 超 10 分钟被踢回登录页（`/auth/refresh` 跨域续期失败，旧代码清 token）。仓库无 `.env.production`，该值仅在 Cloudflare Pages 构建变量中配置，发布前务必人工核对。改后须重新 `wrangler pages deploy` 生效。

---

## 🚀 配置步骤

### **Step 1: 生成安全密钥**

```bash
# 在本地执行
# 生成 INTERNAL_API_SECRET
INTERNAL_SECRET=$(openssl rand -hex 32)
echo "INTERNAL_API_SECRET=$INTERNAL_SECRET"

# 生成 ENCRYPTION_MASTER_KEY
ENCRYPTION_KEY=$(openssl rand -hex 32)
echo "ENCRYPTION_MASTER_KEY=$ENCRYPTION_KEY"
```

**记录这两个值，所有节点都要用！**

---

### **Step 2: 配置本地 `.env`**

编辑 `/Users/stephenhe/Development/workspace/quant_agent/.env`：

```bash
# 添加/修改以下两行
INTERNAL_API_SECRET=<Step 1 生成的值>
ENCRYPTION_MASTER_KEY=<Step 1 生成的值>
```

---

### **Step 3: 配置 Master VPS**

SSH 登录 Master：
```bash
ssh <VPS_USER>@120.53.84.116
cd /opt/quant-agent
sudo nano .env
```

添加/修改：
```bash
INTERNAL_API_SECRET=<Step 1 生成的值>
ENCRYPTION_MASTER_KEY=<Step 1 生成的值>
```

重启服务：
```bash
sudo docker compose restart
```

---

### **Step 4: 配置 Slave-1**

SSH 登录 Slave-1：
```bash
ssh <USER>@<SLAVE-1_IP>
cd /opt/quant-agent
sudo nano .env
```

完整配置：
```bash
NODE_ROLE=slave
COMPOSE_PROFILES=slave

SLAVE_ID=overseas-1
NODE_HOST=<Slave-1 公网 IP>
NODE_PORT=8001

MASTER_NODES=[{"id":"beijing","host":"120.53.84.116","port":6379,"password":"tradingagents123"}]

# 主服务数据源能力默认全开，不再用 COLLECTOR_* 开关；子服务按 DS_CAPABILITIES 声明能力
DATA_SOURCE_ROUTER_ENABLED=true
DS_CAPABILITIES=futu,sentiment

FINNHUB_API_KEY=d2coo7pr01qihtcsq7n0d2coo7pr01qihtcsq7ng
FRED_API_KEY=ff3cb5acfdf642751b1f1aa2d2c450c9

FUTU_HOST=127.0.0.1
FUTU_PORT=11111
FUTU_TRD_ENV=SIMULATE
FUTU_PWD_UNLOCK=

INTERNAL_API_SECRET=<Step 1 生成的值>
ENCRYPTION_MASTER_KEY=<Step 1 生成的值>

QUANT_ENV=production
REAL_TRADE_EXECUTE=false
```

保存并设置权限：
```bash
sudo chmod 600 .env
```

---

### **Step 5: 配置 Slave-2 ~ Slave-4**

对每个 Slave 重复 Step 4，修改以下内容：

| Slave | SLAVE_ID | NODE_HOST | DS_CAPABILITIES |
|-------|----------|-----------|----------------|
| Slave-2 | overseas-2 | <Slave-2 IP> | yfinance |
| Slave-3 | overseas-3 | <Slave-3 IP> | yfinance |
| Slave-4 | overseas-4 | <Slave-4 IP> | yfinance |

**Slave-2~4 简化配置**：
```bash
NODE_ROLE=slave
COMPOSE_PROFILES=slave

SLAVE_ID=overseas-X
NODE_HOST=<Slave-X 公网 IP>
NODE_PORT=8001

MASTER_NODES=[{"id":"beijing","host":"120.53.84.116","port":6379,"password":"tradingagents123"}]

# 子服务仅响应 DS_CAPABILITIES 声明的能力（其余返回 503）；主服务数据源能力默认全开
DS_CAPABILITIES=yfinance

FRED_API_KEY=ff3cb5acfdf642751b1f1aa2d2c450c9

INTERNAL_API_SECRET=<Step 1 生成的值>
ENCRYPTION_MASTER_KEY=<Step 1 生成的值>

QUANT_ENV=production
REAL_TRADE_EXECUTE=false
```

---

### **Step 6: 更新 Master 的 SLAVE_NODES**

SSH 登录 Master，编辑 `/opt/quant-agent/.env`：

```bash
SLAVE_NODES=http://<Slave-1_IP>:8001,http://<Slave-2_IP>:8001,http://<Slave-3_IP>:8001,http://<Slave-4_IP>:8001
```

重启 Master：
```bash
sudo docker compose restart
```

---

### **Step 7: 提交 CI 修改**

在本地执行：
```bash
cd /Users/stephenhe/Development/workspace/quant_agent

# 提交 CI 修改（保留 Slave .env 不被覆盖）
git add .github/workflows/backend.yml
git commit -m "fix(ci): Slave 部署保留已有 .env，不覆盖手动配置"
git push origin develop
```

---

## ✅ 验证检查

### **Master VPS**
```bash
# 检查服务状态
sudo docker ps

# 检查健康状态
curl http://localhost:8000/api/v1/health

# 检查集群状态
curl http://localhost:8000/api/v1/cluster
```

### **Slave-1 ~ Slave-4**
```bash
# 检查服务状态
sudo docker ps

# 检查健康状态
curl http://localhost:8001/health

# 测试 Redis 连接（可选）
redis-cli -h 120.53.84.116 -p 6379 -a tradingagents123 ping
```

---

## 🔥 故障排查

### **问题 1: Slave 无法连接 Master Redis**
```bash
# 在 Slave 上测试
redis-cli -h 120.53.84.116 -p 6379 -a tradingagents123 ping

# 如果失败，检查：
# 1. Master 防火墙是否开放 6379 端口
# 2. Redis 是否监听 0.0.0.0（而非仅 127.0.0.1）
# 3. 云服务商安全组是否放行
```

### **问题 2: Slave 健康检查失败**
```bash
# 查看日志
sudo docker logs quant_slave

# 常见原因：
# - .env 文件不存在或权限不对
# - MASTER_NODES 配置错误
# - 端口 8001 被占用
```

### **问题 3: 集群状态显示 Slave 离线**
```bash
# 在 Master 上检查
curl http://localhost:8000/api/v1/cluster

# 检查 Slave 是否注册到 Redis
redis-cli -a tradingagents123 keys "quant:node:*"
```

### **问题 4: 主服务调子服务 `POST /api/v1/data` 返回 403**
子服务 `verify_hmac`（`data_subservice/main.py`）在两处抛 403，需按以下顺序排查：

1. **HMAC 密钥不一致（最常见）**
   - 子服务仅响应 `DATA_SOURCE_HMAC_SECRET` 与主节点 DataSourceRouter **完全相同**的请求。
   - 检查 Slave 的 `.env` 是否**确实包含** `DATA_SOURCE_HMAC_SECRET`，且值与主节点 `.env` 一字不差：
     ```bash
     # Slave 上：
     grep DATA_SOURCE_HMAC_SECRET /opt/quant-agent/.env
     docker exec <slave-container> printenv DATA_SOURCE_HMAC_SECRET
     # 主节点上：
     grep DATA_SOURCE_HMAC_SECRET /opt/quant-agent/.env
     ```
   - 注意：compose 用 `${DATA_SOURCE_HMAC_SECRET}` 注入，若 Slave 的 `.env` **漏配该变量**，容器内会回退代码默认值 `change-me-in-prod`，与主节点真实密钥不符 → 403。补上后 `docker compose up -d` 重启子服务即可。
   - **⚠️ 双坑（2026-08-13 node-bj 实战）**：
     - **占位符未替换**：`.env.data-node` 若把模板里的 `<与主节点一致的 HMAC 密钥>` **原样保留**（未换成真实哈希），容器 `printenv` 会显示这段中文占位符当密钥，与主节点 `b6fb...` 不符 → 403。注意 `printenv` 回显中文占位符不是打码，是真实配置值。
     - **`.env` 末尾缺换行致 `echo >>` 拼接污染**：修复用 `echo 'KEY=val' >> .env` 时，若文件末行无换行，新内容会拼到上一行（如 `TZ=<时区>DATA_SOURCE_HMAC_SECRET=b6fb...`）。dotenv 把整串解析成 `TZ` 的值，`DATA_SOURCE_HMAC_SECRET` 反未定义 → 容器回退 `change-me-in-prod` → 403 依旧。肉眼 `grep` 能看到哈希却误以为已配。
     - **正确修复**：`printf 'DATA_SOURCE_HMAC_SECRET=<真实哈希>\n' >> .env.data-node`（自带换行），再 `docker compose ... --env-file .env.data-node up -d`，最后 `docker exec <容器> printenv DATA_SOURCE_HMAC_SECRET` 复核必须是纯哈希。

2. **跨 VPS 系统时间差 > 300 秒（隐蔽但高发）**
   - `verify_hmac` 有 `abs(time.time() - int(x_timestamp)) > 300` 的时间窗校验，**早于签名比对执行**。
   - 主节点与 Slave 若未开 NTP 自动校时，时差累计超 5 分钟即触发 403，且**签名本身完全正确也照拒**。
   - 排查：分别在各节点执行 `date +%s`，互相比对，与真实当前时间差应 < 300：
     ```bash
     date +%s
     docker exec <slave-container> date +%s   # 容器共享宿主时钟，通常与宿主一致
     ```
   - 修复（所有节点都执行）：
     ```bash
     sudo timedatectl set-ntp true          # 开启 NTP 自动校时
     # 或老版本：
     sudo apt-get install -y ntpdate && sudo ntpdate pool.ntp.org
     ```
   - 校时**无需重启容器**（容器实时读取宿主时钟）。

3. **缺少 HMAC 请求头**：日志若出现 `缺少 HMAC 请求头`，说明主服务未走 DataSourceRouter 签名路径，检查 `DATA_SOURCE_ROUTER_ENABLED=true` 是否已开启。

> ⚠️ 经验：手动 `sed` 改 compose 后 `up -d` 时，最容易漏掉 Slave `.env` 的 `DATA_SOURCE_HMAC_SECRET`；跨云部署务必确认各节点 NTP 同步。

### **问题 5: 子服务镜像拉取慢 / 被拒（跨境直连 ghcr.io 失败）**
北京/美西等跨境节点直接拉 `ghcr.io/songlinhe5-lab/quant_agent-data-subservice:cn` 会因墙/带宽/未登录而极慢或 `denied`。正确做法是走主节点 S1 的**私有中转 registry（纯 Tailscale 内网，秒级）**。

- **前置（一次性, docker daemon 级）**：在各子节点 `/etc/docker/daemon.json` 配 `insecure-registries`（否则 `pull` 被拒）：
  ```bash
  TS_REG="100.102.223.44:5000"
  DAEMON_CFG="/etc/docker/daemon.json"
  [ -f "$DAEMON_CFG" ] || echo '{}' > "$DAEMON_CFG"
  if ! grep -q "$TS_REG" "$DAEMON_CFG"; then
    sudo jq --arg r "$TS_REG" '. + {insecure-registries: ((.insecure-registries // []) + [$r])}' "$DAEMON_CFG" > /tmp/daemon.json && sudo mv /tmp/daemon.json "$DAEMON_CFG"
    sudo systemctl restart docker
  fi
  ```
- **配置镜像源（推荐, 免手动 sed）**：在节点 `.env.data-node` 加一行，compose 已变量化 `image: ${DATA_SUB_SERVICE_IMAGE:-ghcr.io/...}`：
  ```bash
  echo 'DATA_SUB_SERVICE_IMAGE=100.102.223.44:5000/quant-agent-data-subservice:cn' >> /opt/quant-agent/.env.data-node
  docker compose -f docker-compose.node-bj.yml --env-file .env.data-node up -d
  ```
- **⚠️ 命名空间陷阱**：S1 registry 内实际存储名为 `quant-agent-data-subservice:cn`（CI 推送路径），**不是** ghcr 的 `songlinhe5-lab/quant_agent-data-subservice:cn`。变量值必须用前者，否则 `pull` 报 `manifest unknown`。
- **校验**：`docker pull 100.102.223.44:5000/quant-agent-data-subservice:cn` 应秒级 `Status: Image is up to date / Downloaded`；`docker inspect <容器> --format '{{.Config.Image}}'` 应显示 `100.102.223.44:5000/...`。
- **老方案（不推荐）**：手动 `sed -i 's|ghcr.io/...|100.102.223.44:5000/...|g' docker-compose.node-bj.yml` 再 `up -d`——可临时用，但每次重新部署会被模板覆盖，故改用上面的 `.env` 变量法。

### **问题 6: 前端超 10 分钟被踢回登录页 / 大盘面板空白**

**现象**：登录后静止超过约 10~15 分钟自动跳 `/login`；或 dashboard 大盘无任何数据。

**根因（同一条）**：`VITE_API_BASE_URL` 在 Cloudflare Pages 构建变量里误配成 `https://quant.stephenhe.com/api/v1`（漏 `api-` 子域）。前端访问域 `quant.stephenhe.com` 与 API 域 `quant-api.stephenhe.com` 是 **cross-site**，前者 `/api/*` 被 Cloudflare 拦截（返回 845 字节 HTML 拦截页而非 JSON）。
- REST 业务请求被打到拦截域名 → dashboard 空白。
- `/auth/refresh` 跨域续期失败（旧代码清 token）→ 登录态过期被踢回登录。

**排查**：
1. Cloudflare Pages 控制台 → 项目设置 → 构建与环境变量 → 核对此项目的 `VITE_API_BASE_URL` 是否为 `https://quant-api.stephenhe.com/api/v1`（带 `api-` 子域）。
2. 浏览器 DevTools → Network：看 `POST /auth/refresh` 和 `GET /macro/dashboard` 实际请求 URL 域名，若落在 `quant.stephenhe.com` 即错配。
3. 代码层已做防御（`api-client.ts` 的 `startTokenKeepAlive` 主动续期 + 仅在刷新接口真 401 才清 token），但**错配域名时 REST/refresh 全部落空，代码防御救不了**，必须改部署变量。

**修复**：
- 将 `VITE_API_BASE_URL` 改为 `https://quant-api.stephenhe.com/api/v1`。
- 修改后必须重新部署：Cloudflare Pages 走 `main`/`master` 分支 push 触发 `wrangler pages deploy`（develop push 仅 build 不部署）。
- 仓库无 `.env.production`（该变量不在仓库内），勿在仓库里找，直接看 Pages 控制台。

### **问题 7: sentiment（ApeWisdom 散户热度）源验证 / 全链路排错**

**现象**：主服务 `fetch_sentiment` 返回 `status=error` / 监控里 `sentiment_master` 节点不健康 / `DataSourceRegistry` 查不到 `sentiment`。

**根因与排查顺序**：

1. **子服务未声明 `sentiment` 能力（最常见）**
   - 子服务 `main.py` 的 `_declared_capabilities()` 若 `DS_CAPABILITIES` 未含 `sentiment`，`/api/v1/data?source=sentiment` 直接返回 503「数据源能力未启用」。
   - 主服务 `fetch_sentiment` 收到 503 → 判 `sentiment_master` 节点不健康 → 熔断。
   - 排查：`docker exec <data-subservice容器> printenv DS_CAPABILITIES` 必须含 `sentiment`；若漏，在节点 `.env.data-node` 加 `DS_CAPABILITIES=...,sentiment` 后 `docker compose up -d` 重启子服务。
   - 推荐节点：主节点 S1（同机全能节点，ApeWisdom 免费无 Key、全球可访问）。

2. **`sentiment_master` 后端节点 URL 不可达**
   - 后端 `DataSourceRouter` 的 `sentiment_master` 节点 URL 取 `SENTIMENT_REMOTE_URL`（默认 `http://localhost:8001`），需指向实际子服务地址（S1 同机即 `localhost:8001`，跨节点用 Tailscale IP）。
   - 排查：`curl -s http://<子服务>:8001/health/live` 应返回 healthy。

3. **ApeWisdom 外网不可达 / 429 限流**
   - `apewisdom.py` 直连 `https://apewisdom.io/api/v1.0/...`，免费额度约 30 次/分钟，超频返回 429（错误码 `rate_limit`，不计入熔断失败数，退避期内不硬重试）。
   - 排查（子服务容器内）：`timeout 15 python3 -c "import httpx; print(httpx.get('https://apewisdom.io/api/v1.0/filter/all/page/1', timeout=10).status_code)"` 应返回 200。

**端到端验证（S1 节点实测）**：
```bash
# 1. 子服务能力声明
docker exec quant-agent-node-s1-data-subservice-1 printenv DS_CAPABILITIES | tr ',' '\n' | grep -x sentiment

# 2. 子服务直连 ApeWisdom
docker exec quant-agent-node-s1-data-subservice-1 timeout 15 python3 -c \
  "import httpx; r=httpx.get('https://apewisdom.io/api/v1.0/filter/all/page/1', timeout=10); print('apewisdom', r.status_code, len(r.json().get('data',{}).get('data',[])))"

# 3. 经主服务 fetch_sentiment（HMAC 签名路径）
curl -s -X POST http://localhost:8000/api/v1/data \
  -H "Content-Type: application/json" \
  -d '{"source":"sentiment","action":"TRENDING","params":{"filter":"all","page":1}}' \
  | python3 -m json.tool | head -20
```

---

## 📝 配置记录

**生成时间**: ___________

**INTERNAL_API_SECRET**: ________________________________

**ENCRYPTION_MASTER_KEY**: ________________________________

**Slave-1 IP**: _______________

**Slave-2 IP**: _______________

**Slave-3 IP**: _______________

**Slave-4 IP**: _______________

---

## 🔐 安全提醒

1. ✅ 所有节点的 `INTERNAL_API_SECRET` 和 `ENCRYPTION_MASTER_KEY` 必须一致
2. ✅ 不要将 `.env` 提交到 Git
3. ✅ 定期轮换 API Keys
4. ✅ 生产环境使用强密码（当前 `tradingagents123` 较弱）
5. ✅ 限制 Redis 6379 端口只允许 Slave IP 访问
6. ⚠️ 一旦配置 `ENCRYPTION_MASTER_KEY`，**不要修改**，否则已加密数据无法解密
