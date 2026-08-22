---
kind: external_dependency
name: Yahoo Finance 美股/ETF 数据源
slug: yahoo-finance
category: external_dependency
category_hints:
    - vendor_identity
    - client_constraint
scope:
    - '**'
---

美股与 ETF 行情通过 yfinance 获取，默认在 Docker 镜像中以 `YF_ROUTER_ENABLED=false` 关闭，仅启用声明能力的节点才加载该 worker；通过 DS_CAPABILITIES 控制节点级能力隔离。
