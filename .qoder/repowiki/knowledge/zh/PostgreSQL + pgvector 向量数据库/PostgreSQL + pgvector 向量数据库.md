---
kind: external_dependency
name: PostgreSQL + pgvector 向量数据库
slug: postgresql-pgvector
category: external_dependency
category_hints:
    - vendor_identity
    - client_constraint
scope:
    - '**'
---

`pgvector/pgvector:pg15` 作为主业务数据库与向量检索后端，仅绑定 loopback 与 Tailscale 内网，不暴露公网端口。连接串通过 `DATABASE_URL` 注入，持久化卷名为 `quant_master_postgresql_data`。