"""板块资金流服务单测 (A股/港股聚合 + 美股代理)

零外部依赖: 通过 mock data_source_router.fetch_akshare 与 redis_client 覆盖全部分支。
本地 akshare SDK 已下沉 data_subservice，主服务仅负责远程路由 + 缓存 + 降级。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.datasource.router import data_source_router
from backend.services.fund_flow import a_share_sector, hk_sector, us_sector
from backend.services.fund_flow.a_share_sector import get_a_share_sector_flow
from backend.services.fund_flow.hk_sector import get_hk_sector_flow
from backend.services.fund_flow.service import fund_flow_service


def _fake_redis(get_return=None, set_raise=False):
    m = AsyncMock()
    m.get = AsyncMock(return_value=get_return)
    if set_raise:
        m.set = AsyncMock(side_effect=RuntimeError("redis down"))
    else:
        m.set = AsyncMock(return_value=True)
    return m


def _fake_fetch(action_result: dict):
    """构造一个返回指定结果的 fetch_akshare mock。"""
    m = AsyncMock(return_value=action_result)
    return m


# ============================ A 股板块 ============================


def test_a_share_cache_hit():
    cached = json.dumps({"status": "success", "data": {"market": "A_SHARE"}})
    with patch.object(a_share_sector, "redis_client", _fake_redis(get_return=cached)):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert res["data"]["market"] == "A_SHARE"


def test_a_share_success_standard_columns():
    payload = {
        "status": "success",
        "data": {
            "market": "A_SHARE",
            "market_name": "A股行业",
            "inflow_top": [
                {"name": "银行", "change_pct": 1.5, "main_net_inflow": 100.0, "main_net_pct": 3.2},
                {"name": "券商", "change_pct": -2.0, "main_net_inflow": -50.0, "main_net_pct": -1.1},
            ],
            "outflow_top": [],
            "unit": "万元",
            "source": "AKShare (东方财富)",
        },
        "source": "akshare_stock_sector_fund_flow_rank",
    }
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch.object(data_source_router, "fetch_akshare", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert len(res["data"]["inflow_top"]) == 2
    assert res["data"]["inflow_top"][0]["name"] == "银行"


def test_a_share_empty_df():
    payload = {"status": "error", "message": "AKShare 返回空数据", "data": None}
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch.object(data_source_router, "fetch_akshare", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "error"


def test_a_share_akshare_raises():
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch.object(data_source_router, "fetch_akshare", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "error"


def test_a_share_cache_write_failure_silent():
    payload = {
        "status": "success",
        "data": {
            "market": "A_SHARE",
            "market_name": "A股行业",
            "inflow_top": [{"name": "银行", "change_pct": 1.0, "main_net_inflow": 0.01, "main_net_pct": 1.0}],
            "outflow_top": [],
            "unit": "万元",
            "source": "AKShare (东方财富)",
        },
        "source": "akshare_stock_sector_fund_flow_rank",
    }
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis(set_raise=True)),
        patch.object(data_source_router, "fetch_akshare", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    # 缓存写入失败不影响主流程
    assert res["status"] == "success"


def test_a_share_redis_get_raises_silent():
    # redis 读取异常被吞, 回退到远程 fetch (覆盖 44-46)
    rc = AsyncMock()
    rc.get = AsyncMock(side_effect=RuntimeError("redis boom"))
    rc.set = AsyncMock(return_value=True)
    payload = {
        "status": "success",
        "data": {
            "market": "A_SHARE",
            "market_name": "A股行业",
            "inflow_top": [{"name": "银行", "change_pct": 1.0, "main_net_inflow": 0.01, "main_net_pct": 1.0}],
            "outflow_top": [],
            "unit": "万元",
            "source": "AKShare (东方财富)",
        },
        "source": "akshare_stock_sector_fund_flow_rank",
    }
    with (
        patch.object(a_share_sector, "redis_client", rc),
        patch.object(data_source_router, "fetch_akshare", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"


def test_a_share_stale_fallback():
    # 远程失败但有 STALE 缓存 -> 返回降级数据 (覆盖 stale 分支)
    stale = json.dumps({"status": "success", "data": {"market": "A_SHARE"}})
    rc = AsyncMock()
    rc.get = AsyncMock(side_effect=[None, stale])
    rc.set = AsyncMock(return_value=True)
    with (
        patch.object(a_share_sector, "redis_client", rc),
        patch.object(data_source_router, "fetch_akshare", AsyncMock(side_effect=RuntimeError("ak boom"))),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert res["stale"] is True


# ============================ 港股板块 ============================


def test_hk_success():
    payload = {
        "status": "success",
        "data": {
            "market": "HK",
            "market_name": "港股行业板块",
            "sectors": [
                {"name": "科技", "net_inflow": 100.0, "pct": 0.6},
                {"name": "金融", "net_inflow": -50.0, "pct": 0.4},
            ],
            "unit": "港元",
            "note": "由各板块龙头成分股主力净流入聚合，仅供参考",
            "source": "Futu",
        },
        "source": "futu",
    }
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch.object(data_source_router, "fetch_futu", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"
    assert len(res["data"]["sectors"]) == 2


def test_hk_empty_df():
    payload = {"status": "error", "message": "Futu 港股板块资金流失败", "data": None}
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch.object(data_source_router, "fetch_futu", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "degraded"


def test_hk_futu_raises():
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch.object(data_source_router, "fetch_futu", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "degraded"


def test_hk_redis_get_raises_silent():
    # redis 读取异常被吞, 回退到远程 fetch
    rc = AsyncMock()
    rc.get = AsyncMock(side_effect=RuntimeError("redis boom"))
    rc.set = AsyncMock(return_value=True)
    payload = {
        "status": "success",
        "data": {
            "market": "HK",
            "market_name": "港股行业板块",
            "sectors": [{"name": "科技", "net_inflow": 100.0, "pct": 1.0}],
            "unit": "港元",
            "note": "由各板块龙头成分股主力净流入聚合，仅供参考",
            "source": "Futu",
        },
        "source": "futu",
    }
    with (
        patch.object(hk_sector, "redis_client", rc),
        patch.object(data_source_router, "fetch_futu", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"


def test_hk_cache_write_failure_silent():
    # 缓存写入失败不影响主流程
    rc = AsyncMock()
    rc.get = AsyncMock(return_value=None)
    rc.set = AsyncMock(side_effect=RuntimeError("redis boom"))
    payload = {
        "status": "success",
        "data": {
            "market": "HK",
            "market_name": "港股行业板块",
            "sectors": [{"name": "科技", "net_inflow": 100.0, "pct": 1.0}],
            "unit": "港元",
            "note": "由各板块龙头成分股主力净流入聚合，仅供参考",
            "source": "Futu",
        },
        "source": "futu",
    }
    with (
        patch.object(hk_sector, "redis_client", rc),
        patch.object(data_source_router, "fetch_futu", _fake_fetch(payload)),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"


# ============================ 美股板块 (Futu 代理) ============================


def test_us_sector_success_via_market_data():
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {"main_fund_net_inflow": 1.5e8}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {}
    with (
        patch("backend.app.macro_app.manager", create=True, new=fake_manager),
        patch("backend.app.macro_app.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    assert len(res["data"]["sectors"]) == 11  # 标准 GICS 11 大行业
    xlf = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.XLF")
    assert xlf["net_inflow"] == 1.5  # 1.5e8 -> 1.5 亿美元
    assert xlf["dir"] == 1


def test_us_sector_cache_hit():
    # 仅信任权威字段 main_fund_net_inflow（单位：元），9e8 元 = 9.0 亿美元
    cached = {"data": {"main_fund_net_inflow": 9.0e8}}
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {"main_fund_net_inflow": 0}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {"US.XLF": cached}
    with (
        patch("backend.app.macro_app.manager", create=True, new=fake_manager),
        patch("backend.app.macro_app.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    spy = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.XLF")
    assert spy["net_inflow"] == 9.0


def test_us_sector_one_ticker_fails():
    def _side(ticker):
        if ticker == "US.XLRE":
            raise RuntimeError("futu down")
        return {"data": {"main_fund_net_inflow": 1.0e8}}

    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(side_effect=_side)
    fake_manager = MagicMock()
    fake_manager.flow_cache = {}
    with (
        patch("backend.app.macro_app.manager", create=True, new=fake_manager),
        patch("backend.app.macro_app.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    tickers = [s["ticker"] for s in res["data"]["sectors"]]
    assert "US.XLRE" not in tickers  # 失败的 ETF 被跳过


def test_us_sector_ignores_legacy_fields():
    # 历史脏结构：net_inflow/net_amount 字段存在但单位错乱，必须忽略，只取 main_fund_net_inflow
    cached = {"data": {"net_inflow": 8.88e12, "net_amount": 7.6e13, "main_fund_net_inflow": 2.6e6}}
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {"US.XLRE": cached}
    with (
        patch("backend.app.macro_app.manager", create=True, new=fake_manager),
        patch("backend.app.macro_app.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    spy = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.XLRE")
    # 2.6e6 元 = 0.026 亿美元，且绝不能出现 88809 亿这类脏值
    assert spy["net_inflow"] == 0.03 or abs(spy["net_inflow"] - 0.026) < 0.01
    assert spy["net_inflow"] < 1.0  # 明确排除脏值量级


def test_us_sector_dirty_value_boundary():
    # 上游返回超过 1 万亿（元）的异常值，必须被边界降级为 0，杜绝 88809 亿进面板
    cached = {"data": {"main_fund_net_inflow": 8.880933e12}}
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {"US.XLB": cached}
    with (
        patch("backend.app.macro_app.manager", create=True, new=fake_manager),
        patch("backend.app.macro_app.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    spy = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.XLB")
    assert spy["net_inflow"] == 0.0


# ============================ 聚合服务 ============================


def test_service_all_success():
    a = {"status": "success", "data": {"market": "A_SHARE"}}
    h = {"status": "success", "data": {"market": "HK"}}
    u = {"status": "success", "data": {"market": "US"}}
    with (
        patch("backend.services.fund_flow.service.get_a_share_sector_flow", AsyncMock(return_value=a)),
        patch("backend.services.fund_flow.service.get_hk_sector_flow", AsyncMock(return_value=h)),
        patch("backend.services.fund_flow.service.get_us_sector_flow", AsyncMock(return_value=u)),
    ):
        res = asyncio.run(fund_flow_service.get_sector_fund_flow())
    assert res["status"] == "success"
    assert res["data"]["a_share"] == a
    assert res["data"]["hk"] == h
    assert res["data"]["us"] == u


def test_service_partial():
    h = {"status": "success", "data": {}}
    u = {"status": "success", "data": {}}
    with (
        patch(
            "backend.services.fund_flow.service.get_a_share_sector_flow",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch("backend.services.fund_flow.service.get_hk_sector_flow", AsyncMock(return_value=h)),
        patch("backend.services.fund_flow.service.get_us_sector_flow", AsyncMock(return_value=u)),
    ):
        res = asyncio.run(fund_flow_service.get_sector_fund_flow())
    assert res["status"] == "partial"


def test_service_all_error():
    with (
        patch(
            "backend.services.fund_flow.service.get_a_share_sector_flow",
            AsyncMock(side_effect=RuntimeError("e1")),
        ),
        patch("backend.services.fund_flow.service.get_hk_sector_flow", AsyncMock(side_effect=RuntimeError("e2"))),
        patch(
            "backend.services.fund_flow.service.get_us_sector_flow",
            AsyncMock(side_effect=RuntimeError("e3")),
        ),
    ):
        res = asyncio.run(fund_flow_service.get_sector_fund_flow())
    assert res["status"] == "error"
