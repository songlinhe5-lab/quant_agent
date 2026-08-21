---
kind: external_dependency
name: Redis 缓存与会话存储
slug: redis
category: external_dependency
category_hints:
    - vendor_identity
    - client_constraint
scope:
    - '**'
---

Redis 7 Alpine 作为主服务缓存、会话与队列中间件，容器内绑定 loopback 与 Tailscale 内网 IP（不暴露公网），密码通过 `REDIS_PASSWORD` 注入。主服务与 worker 通过 Docker 内部服务名 `redis` 通信。