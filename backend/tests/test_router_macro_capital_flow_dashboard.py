"""FUNDFLOW-01: routers/macro.py capital-flow-dashboard 端点测试

覆盖: GET /api/v1/macro/capital-flow-dashboard 聚合北向/南向 + 三市场板块资金流。
"""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _north(scale=1.0):
    return {
        "status": "success",
        "data": {
            "net_inflow": -5.3 * scale,
            "weekly": -12.1 * scale,
            "monthly": 30.5 * scale,
            "unit": "亿人民币",
            "date": "2026-07-29",
            "sparkline": [-1, -1, 1, -1, -1, 1, -1, -1],
            "history": [-1.0, -2.0, 3.0, -1.0, -1.0, 1.0, -1.0, -1.0],
        },
    }


def _south(scale=1.0):
    return {
        "status": "success",
        "data": {
            "net_inflow": 12.8 * scale,
            "weekly": 40.2 * scale,
            "monthly": -8.4 * scale,
            "unit": "亿人民币",
            "date": "2026-07-29",
            "sparkline": [1, 1, -1, 1, 1, 1, -1, 1],
            "history": [1.0, 2.0, -1.0, 1.0, 1.0, 1.0, -1.0, 1.0],
        },
    }


def _sectors():
    return {
        "status": "success",
        "data": {
            "a_share": {
                "status": "success",
                "data": {
                    "inflow_top": [
                        {"名称": "半导体", "主力净流入": "25.3", "涨跌幅": "2.1"},
                        {"名称": "白酒", "主力净流入": "12.0", "涨跌幅": "-0.5"},
                    ],
                    "unit": "亿",
                    "updated_at": "2026-07-29T08:00:00Z",
                    "source": "akshare",
                },
            },
            "hk": {
                "status": "success",
                "data": {
                    "sectors": [
                        {"name": "资讯科技业", "net_inflow": 8.4},
                        {"name": "金融业", "net_inflow": -3.1},
                    ],
                    "unit": "亿港元",
                },
            },
            "us": {
                "status": "success",
                "data": {
                    "sectors": [
                        {"name": "Technology", "net_inflow": 120.5},
                        {"name": "Energy", "net_inflow": -45.2},
                    ],
                    "unit": "百万美元",
                },
            },
        },
    }


class TestCapitalFlowDashboard:
    def test_dashboard_aggregates_all_markets(self, client):
        """聚合器正常:北向/南向/三市场板块均返回并落入标准结构"""
        with (
            patch("backend.app.macro_app.redis_client") as m_redis,
            patch("backend.app.macro_app.market_data.get_northbound_flow", new=AsyncMock(side_effect=_north)),
            patch("backend.app.macro_app.market_data.get_southbound_flow", new=AsyncMock(side_effect=_south)),
            patch("backend.app.macro_app.get_sector_fund_flow", new=AsyncMock(return_value=_sectors())),
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/macro/capital-flow-dashboard")

        assert resp.status_code == 200
        body = resp.json()
        data = body.get("data", body)
        assert data["status"] == "success"
        assert data["data"]["northbound"]["net_inflow"] == pytest.approx(-5.3)
        assert data["data"]["northbound"]["weekly"] == pytest.approx(-12.1)
        assert data["data"]["northbound"]["monthly"] == pytest.approx(30.5)
        assert data["data"]["southbound"]["net_inflow"] == pytest.approx(12.8)
        # A股行业分布:名称 + 数值
        a_sectors = data["data"]["a_share"]["sectors"]
        assert a_sectors[0]["name"] == "半导体"
        assert a_sectors[0]["net_inflow"] == pytest.approx(25.3)
        assert a_sectors[0]["change_pct"] == pytest.approx(2.1)
        # 港股/美股板块
        assert data["data"]["hk"]["sectors"][0]["name"] == "资讯科技业"
        assert data["data"]["us"]["sectors"][0]["net_inflow"] == pytest.approx(120.5)

    def test_dashboard_partial_when_subtasks_fail(self, client):
        """子任务降级:北向/板块失败只返回南向,status 仍为 success(any_ok)"""
        with (
            patch("backend.app.macro_app.redis_client") as m_redis,
            patch(
                "backend.app.macro_app.market_data.get_northbound_flow",
                new=AsyncMock(return_value={"status": "no_data", "data": None}),
            ),
            patch("backend.app.macro_app.market_data.get_southbound_flow", new=AsyncMock(side_effect=_south)),
            patch(
                "backend.app.macro_app.get_sector_fund_flow",
                new=AsyncMock(return_value={"status": "warning", "data": None}),
            ),
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/macro/capital-flow-dashboard")

        assert resp.status_code == 200
        body = resp.json()
        data = body.get("data", body)
        assert data["status"] == "success"
        assert data["data"]["northbound"] is None
        assert data["data"]["a_share"] is None
        assert data["data"]["southbound"]["net_inflow"] == pytest.approx(12.8)

    def test_dashboard_warning_when_all_fail(self, client):
        """全部失败:诚实返回 warning,不注入假数据"""
        with (
            patch("backend.app.macro_app.redis_client") as m_redis,
            patch(
                "backend.app.macro_app.market_data.get_northbound_flow",
                new=AsyncMock(side_effect=Exception("网络错误")),
            ),
            patch(
                "backend.app.macro_app.market_data.get_southbound_flow",
                new=AsyncMock(side_effect=Exception("网络错误")),
            ),
            patch("backend.app.macro_app.get_sector_fund_flow", new=AsyncMock(side_effect=Exception("网络错误"))),
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/macro/capital-flow-dashboard")

        assert resp.status_code == 200
        body = resp.json()
        data = body.get("data", body)
        assert data["status"] == "warning"
        assert data["data"]["northbound"] is None
        assert data["data"]["southbound"] is None
