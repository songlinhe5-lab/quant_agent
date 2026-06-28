import asyncio
import hashlib
import json
import random
from typing import Any, Dict, List

from sqlalchemy import Column, String

from backend.core.database import Base, SessionLocal, engine
from backend.core.redis_client import redis_client
from backend.services.futu import futu_service


class TickerItem(Base):
    """定义持久化的股票词库 SQLAlchemy 数据模型"""
    __tablename__ = "tickers"
    symbol = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    market = Column(String)
    type = Column(String)

class TickerService:
    """
    股票词库服务 (基于 PostgreSQL/SQLite + Redis 双级架构)
    提供数据库持久化存储全市场标的，以及 Redis 毫秒级缓存热门搜索。
    """
    def __init__(self):
        self.sync_running = False
        self._search_locks = {}

    async def search_tickers(self, query: str) -> Dict[str, Any]:
        # 💡 防御超长恶意输入：限制最大长度防范字典内存溢出
        if not query or len(query) > 50:
            return {"status": "success", "data": []}

        query_upper = query.strip().upper()
        # 💡 修复脏数据漏洞：对任意用户输入进行 Hash，彻底阻断由于空格、冒号、换行符等引发的 Redis 命名空间污染  # noqa: E501
        query_hash = hashlib.md5(query_upper.encode('utf-8')).hexdigest()
        cache_key = f"quant:tickers:search:{query_hash}"

        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return {"status": "success", "data": json.loads(cached)}

            if cache_key not in self._search_locks:
                self._search_locks[cache_key] = asyncio.Lock()

            async with self._search_locks[cache_key]:
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return {"status": "success", "data": json.loads(cached_double)}

                def _db_query():
                    from sqlalchemy import case, func, or_
                    with SessionLocal() as db:
                        is_pg = engine.dialect.name == 'postgresql'

                        if is_pg:
                            # 1. 生产环境 PostgreSQL: 开启 pg_trgm 相似度评分 (容忍拼写错误)  # noqa: E501
                            sim_symbol = func.similarity(TickerItem.symbol, query_upper)
                            sim_name = func.similarity(TickerItem.name, query_upper)

                            rows = db.query(TickerItem).filter(
                                or_(
                                    TickerItem.symbol.ilike(f"%{query_upper}%"),
                                    TickerItem.name.ilike(f"%{query_upper}%"),
                                    sim_symbol > 0.15,  # 相似度 > 0.15 即被召回 (容忍 APPL -> AAPL)  # noqa: E501
                                    sim_name > 0.15
                                )
                            ).order_by(
                                # 排序权重: 绝对等于排最前 > 代码相似度 > 名称相似度 > 字符串越短越精准  # noqa: E501
                                case((TickerItem.symbol == query_upper, 0), else_=1),
                                sim_symbol.desc(),
                                sim_name.desc(),
                                func.length(TickerItem.symbol)
                            ).limit(10).all()
                        else:
                            # 2. 开发环境 SQLite 兜底: 智能前缀权重排序
                            rows = db.query(TickerItem).filter(
                                or_(TickerItem.symbol.ilike(f"%{query_upper}%"), TickerItem.name.ilike(f"%{query_upper}%"))  # noqa: E501
                            ).order_by(
                                case((TickerItem.symbol == query_upper, 0), else_=1),
                                case((TickerItem.symbol.ilike(f"{query_upper}%"), 0), else_=1),  # noqa: E501
                                func.length(TickerItem.symbol)
                            ).limit(10).all()

                        return [{"symbol": r.symbol, "name": r.name, "type": r.type} for r in rows]  # noqa: E501

                results = await asyncio.to_thread(_db_query)
                if results:
                    ttl = 3600 + random.randint(60, 300)
                    await redis_client.set(cache_key, json.dumps(results), ex=ttl)
                return {"status": "success", "data": results}
        except Exception as e:
            return {"status": "error", "message": f"本地词库 SQL 搜索异常: {e}"}

    async def sync_tickers_daemon(self):
        """作为守护协程在后台运行，定期执行同步"""
        if self.sync_running:
            return
        self.sync_running = True

        while True:
            try:
                print("🔄 [Ticker Sync] 正在同步全市场股票词库至数据库...")
                await asyncio.to_thread(self._write_base_tickers)

                if futu_service.status == "CONNECTED":
                    await self._fetch_and_save_from_futu()
                    print("✅ [Ticker Sync] 股票词库同步完成，Redis 缓存 + DB 持久化就绪！")  # noqa: E501
                else:
                    print("⚠️ [Ticker Sync] FutuService 未连接，跳过全市场增量同步。")
            except Exception as e:
                print(f"⚠️ [Ticker Sync] 词库同步暂不可用 (将在后台定期重试): {e}")

            # 每天执行一次全量同步更新 (86400 秒)
            await asyncio.sleep(86400)

    def _write_base_tickers(self) -> List[Dict[str, Any]]:
        base_tickers = [
            {"symbol": "HK.800000", "name": "恒生指数", "market": "HK", "type": "INDEX"},  # noqa: E501
            {"symbol": "HK.800700", "name": "恒生科技指数", "market": "HK", "type": "INDEX"},  # noqa: E501
            {"symbol": "US.SPX", "name": "标普500", "market": "US", "type": "INDEX"},
            {"symbol": "US.NDX", "name": "纳斯达克100", "market": "US", "type": "INDEX"},  # noqa: E501
            {"symbol": "US.AAPL", "name": "Apple Inc.", "market": "US", "type": "EQUITY"},  # noqa: E501
            {"symbol": "US.TSLA", "name": "Tesla Inc.", "market": "US", "type": "EQUITY"},  # noqa: E501
            {"symbol": "US.NVDA", "name": "NVIDIA Corporation", "market": "US", "type": "EQUITY"},  # noqa: E501
            {"symbol": "HK.00700", "name": "腾讯控股", "market": "HK", "type": "EQUITY"},  # noqa: E501
        ]
        with SessionLocal() as db:
            for item in base_tickers:
                db.merge(TickerItem(**item))
            db.commit()
        return base_tickers

    async def _fetch_and_save_from_futu(self) -> List[Dict[str, Any]]:
        tickers_to_insert = []
        for market in ["HK", "US"]:
            for sec_type in ["STOCK", "ETF"]:
                res = await futu_service.get_stock_basicinfo(market, sec_type)
                if res.get("status") == "success":
                    for row in res.get("data", []):
                        code = row.get('code', '')
                        # 💡 修复：直接使用富途官方带前缀的代码作为唯一标识
                        symbol = code
                        if not symbol: continue  # noqa: E701

                        tickers_to_insert.append({
                            "symbol": symbol, "name": row.get('name', ''),
                            "market": market, "type": "EQUITY" if sec_type == "STOCK" else "ETF"  # noqa: E501
                        })

        if tickers_to_insert:
            def _bulk_upsert():
                with SessionLocal() as db:
                    for item in tickers_to_insert:
                        db.merge(TickerItem(**item))
                    db.commit()
            await asyncio.to_thread(_bulk_upsert)
        return tickers_to_insert

ticker_service = TickerService()
