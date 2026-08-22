---
kind: external_dependency
name: Tushare A 股主数据源
slug: tushare
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
---

A 股历史 K 线、财务等数据通过 Tushare Pro 获取，需 2000 积分 / 200 元档权限。以独立 worker 进程运行于 data_subservice，经 DataSourceRouter 对外暴露。
