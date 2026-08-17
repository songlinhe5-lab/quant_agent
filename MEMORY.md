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
