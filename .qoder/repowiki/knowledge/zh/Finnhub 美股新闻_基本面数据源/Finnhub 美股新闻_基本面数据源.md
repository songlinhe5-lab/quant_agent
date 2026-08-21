---
kind: external_dependency
name: Finnhub 美股新闻/基本面数据源
slug: finnhub
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
---

美股新闻与基本面数据通过 Finnhub 获取，其配额耗尽时会触发飞书告警（SVC-05），接入 OBS-02 监控体系。