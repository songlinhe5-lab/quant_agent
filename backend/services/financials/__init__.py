"""
FIN-03 · 财报事实层存储
=======================

`repository`：PG 读写（双时间轴幂等写入 + PIT 查询 + 重述清单）
`parquet_store`：多期宽表落盘（docs/19 快照目录）

采集在 `data_subservice`（FIN-01）、归一化在 `domain/financials`（FIN-02）、
对外 API 与编排在 FIN-04。
"""
