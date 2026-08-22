"""Sentiment 散户情绪数据源（物理解耦裁剪版）。

目前仅 ApeWisdom（散户社交媒体热度榜），无 API Key、免费可用。
主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=sentiment) 访问本实现。
"""
