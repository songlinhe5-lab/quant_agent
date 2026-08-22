---
kind: external_dependency
name: AkShare A 股兜底数据源
slug: akshare
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
---

当 Tushare 不可用或无权限时，AkShare（基于新浪源）作为 A 股数据的兜底来源，同样以 data_subservice worker 形式提供 HTTP 接口。
