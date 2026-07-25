"""板块资金流服务单测 (A股/港股聚合 + 美股代理)

零外部依赖: 通过 mock akshare 与 redis_client 覆盖全部分支。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

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


# ============================ A 股板块 ============================


def test_a_share_cache_hit():
    cached = json.dumps({"status": "success", "data": {"market": "A_SHARE"}})
    with patch.object(a_share_sector, "redis_client", _fake_redis(get_return=cached)):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert res["data"]["market"] == "A_SHARE"


def test_a_share_success_standard_columns():
    df = pd.DataFrame(
        {
            "名称": ["银行", "券商"],
            "今日涨跌幅": [1.5, -2.0],
            "今日主力净流入-净额": [1_000_000.0, -500_000.0],
            "今日主力净流入-净占比": [3.2, -1.1],
        }
    )
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_sector_fund_flow_rank", return_value=df),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert len(res["data"]["inflow_top"]) == 2
    assert res["data"]["inflow_top"][0]["name"] == "银行"


def test_a_share_success_compat_columns():
    # 字段名与默认不一致, 触发兼容字段名探测循环 (lines 66-80)
    df = pd.DataFrame(
        {
            "主力净流入净额": [800_000.0, 200_000.0],
            "主力净流入净占比": [2.0, 0.5],
            "涨跌幅": [0.5, -0.3],
            "板块名": ["医药", "消费"],
        }
    )
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_sector_fund_flow_rank", return_value=df),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert res["data"]["inflow_top"][0]["main_net_inflow"] == 80.0


def test_a_share_empty_df():
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_sector_fund_flow_rank", return_value=pd.DataFrame()),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "error"


def test_a_share_akshare_raises():
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_sector_fund_flow_rank", side_effect=RuntimeError("boom")),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "error"


def test_a_share_cache_write_failure_silent():
    df = pd.DataFrame(
        {
            "名称": ["银行"],
            "今日涨跌幅": [1.0],
            "今日主力净流入-净额": [100.0],
            "今日主力净流入-净占比": [1.0],
        }
    )
    with (
        patch.object(a_share_sector, "redis_client", _fake_redis(set_raise=True)),
        patch("akshare.stock_sector_fund_flow_rank", return_value=df),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    # 缓存写入失败不影响主流程
    assert res["status"] == "success"


def test_a_share_redis_get_raises_silent():
    # redis 读取异常被吞, 回退到 akshare (覆盖 43-44)
    rc = AsyncMock()
    rc.get = AsyncMock(side_effect=RuntimeError("redis boom"))
    rc.set = AsyncMock(return_value=True)
    df = pd.DataFrame(
        {
            "名称": ["银行"],
            "今日涨跌幅": [1.0],
            "今日主力净流入-净额": [100.0],
            "今日主力净流入-净占比": [1.0],
        }
    )
    with (
        patch.object(a_share_sector, "redis_client", rc),
        patch("akshare.stock_sector_fund_flow_rank", return_value=df),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"


def test_a_share_stale_fallback():
    # akshare 失败但有 STALE 缓存 -> 返回降级数据 (覆盖 121-127)
    stale = json.dumps({"status": "success", "data": {"market": "A_SHARE"}})
    rc = AsyncMock()
    rc.get = AsyncMock(side_effect=[None, stale])
    rc.set = AsyncMock(return_value=True)
    with (
        patch.object(a_share_sector, "redis_client", rc),
        patch("akshare.stock_sector_fund_flow_rank", side_effect=RuntimeError("ak boom")),
    ):
        res = asyncio.run(get_a_share_sector_flow())
    assert res["status"] == "success"
    assert res["stale"] is True


# ============================ 港股板块 ============================


def test_hk_success():
    df = pd.DataFrame({"行业": ["科技", "金融"], "净买入": [1e6, -5e5]})
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_hsgt_fund_flow_summary_em", return_value=df),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"
    assert len(res["data"]["sectors"]) == 2


def test_hk_empty_df():
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_hsgt_fund_flow_summary_em", return_value=pd.DataFrame()),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "degraded"


def test_hk_generic_parse():
    # 字段名不匹配候选, 但存在可解析的数值列 -> 通用解析分支
    df = pd.DataFrame({"板块": ["A", "B"], "资金": [100.0, 200.0]})
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_hsgt_fund_flow_summary_em", return_value=df),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"
    # 按资金净流入降序: B(200) 在 A(100) 之前
    assert res["data"]["sectors"][0]["name"] == "B"


def test_hk_no_parseable_columns():
    # 单列且非数值 -> 无法解析 -> 降级
    df = pd.DataFrame({"foo": ["x"]})
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_hsgt_fund_flow_summary_em", return_value=df),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "degraded"


def test_hk_akshare_raises():
    with (
        patch.object(hk_sector, "redis_client", _fake_redis()),
        patch("akshare.stock_hsgt_fund_flow_summary_em", side_effect=RuntimeError("boom")),
    ):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "degraded"


def test_hk_redis_get_raises_silent():
    # redis 读取异常被吞, 回退到 akshare (覆盖 44-46)
    rc = AsyncMock()
    rc.get = AsyncMock(side_effect=RuntimeError("redis boom"))
    rc.set = AsyncMock(return_value=True)
    df = pd.DataFrame({"行业": ["科技"], "净买入": [1e6]})
    with patch.object(hk_sector, "redis_client", rc), patch("akshare.stock_hsgt_fund_flow_summary_em", return_value=df):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"


def test_hk_cache_write_failure_silent():
    # 缓存写入失败不影响主流程 (覆盖 80-81)
    rc = AsyncMock()
    rc.get = AsyncMock(return_value=None)
    rc.set = AsyncMock(side_effect=RuntimeError("redis boom"))
    df = pd.DataFrame({"行业": ["科技"], "净买入": [1e6]})
    with patch.object(hk_sector, "redis_client", rc), patch("akshare.stock_hsgt_fund_flow_summary_em", return_value=df):
        res = asyncio.run(get_hk_sector_flow())
    assert res["status"] == "success"


# ============================ 美股板块 (Futu 代理) ============================


def test_us_sector_success_via_market_data():
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {"net_inflow": 1.5e8}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {}
    with (
        patch("backend.routers.macro.manager", create=True, new=fake_manager),
        patch("backend.routers.macro.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    assert len(res["data"]["sectors"]) == 8
    spy = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.SPY")
    assert spy["net_inflow"] == 1.5  # 1.5e8 -> 1.5 亿美元
    assert spy["dir"] == 1


def test_us_sector_cache_hit():
    cached = {"data": {"net_inflow": 9.0e8}}
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {"net_inflow": 0}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {"US.SPY": cached}
    with (
        patch("backend.routers.macro.manager", create=True, new=fake_manager),
        patch("backend.routers.macro.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    spy = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.SPY")
    assert spy["net_inflow"] == 9.0


def test_us_sector_one_ticker_fails():
    def _side(ticker):
        if ticker == "US.QQQ":
            raise RuntimeError("futu down")
        return {"data": {"net_inflow": 1.0e8}}

    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(side_effect=_side)
    fake_manager = MagicMock()
    fake_manager.flow_cache = {}
    with (
        patch("backend.routers.macro.manager", create=True, new=fake_manager),
        patch("backend.routers.macro.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    tickers = [s["ticker"] for s in res["data"]["sectors"]]
    assert "US.QQQ" not in tickers  # 失败的 ETF 被跳过


def test_us_sector_nested_capital_flow():
    fake_market = MagicMock()
    fake_market.get_fund_flow = AsyncMock(return_value={"data": {"capital_flow": {"net_amount": 2.0e8}}})
    fake_manager = MagicMock()
    fake_manager.flow_cache = {}
    with (
        patch("backend.routers.macro.manager", create=True, new=fake_manager),
        patch("backend.routers.macro.market_data", create=True, new=fake_market),
    ):
        res = asyncio.run(us_sector.get_us_sector_flow())
    assert res["status"] == "success"
    spy = next(s for s in res["data"]["sectors"] if s["ticker"] == "US.SPY")
    assert spy["net_inflow"] == 2.0


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
