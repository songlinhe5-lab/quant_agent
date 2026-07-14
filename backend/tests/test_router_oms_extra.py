"""routers/oms.py 补充单元测试

覆盖: bots pause/resume/stop, algo start/pause/resume/cancel, trading mode, websocket
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


def _unwrap(resp):
    body = resp.json()
    return body.get("data", body)


# ==========================================
# POST /api/v1/oms/bots/{bot_id}/pause
# ==========================================
class TestOmsBotControl:
    @patch("backend.routers.oms.bot_runtime")
    def test_pause_bot_success(self, mock_bot):
        mock_bot.pause_bot = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/bots/test-bot-1/pause")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "已暂停" in data["message"]

    @patch("backend.routers.oms.bot_runtime")
    def test_pause_bot_not_running(self, mock_bot):
        mock_bot.pause_bot = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/bots/test-bot-1/pause")
        assert resp.status_code == 400

    @patch("backend.routers.oms.bot_runtime")
    def test_resume_bot_success(self, mock_bot):
        mock_bot.resume_bot = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/bots/test-bot-1/resume")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "已恢复" in data["message"]

    @patch("backend.routers.oms.bot_runtime")
    def test_resume_bot_not_paused(self, mock_bot):
        mock_bot.resume_bot = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/bots/test-bot-1/resume")
        assert resp.status_code == 400

    @patch("backend.routers.oms.bot_runtime")
    def test_stop_bot_success(self, mock_bot):
        mock_bot.stop_bot = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/bots/test-bot-1/stop")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "已终止" in data["message"]

    @patch("backend.routers.oms.bot_runtime")
    def test_stop_bot_not_found(self, mock_bot):
        mock_bot.stop_bot = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/bots/test-bot-1/stop")
        assert resp.status_code == 400


# ==========================================
# POST /api/v1/oms/algo/start
# ==========================================
class TestOmsAlgoControl:
    @patch("backend.routers.oms.algo_engine")
    @patch("backend.routers.oms.log_audit")
    def test_start_algo_success(self, mock_audit, mock_engine):
        mock_order = MagicMock()
        mock_order.algo_id = "algo-1"
        mock_order.to_api_dict.return_value = {"algo_id": "algo-1", "algo_type": "TWAP"}
        mock_engine.start_algo = AsyncMock(return_value=mock_order)

        with patch("backend.core.database.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            client = TestClient(app)
            resp = client.post(
                "/api/v1/oms/algo/start",
                json={"algo_type": "TWAP", "symbol": "AAPL", "side": "BUY", "target_qty": 100, "duration_minutes": 30},
            )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"]["algo_id"] == "algo-1"

    @patch("backend.routers.oms.algo_engine")
    def test_start_algo_error(self, mock_engine):
        mock_engine.start_algo = AsyncMock(side_effect=Exception("参数错误"))
        client = TestClient(app)
        resp = client.post(
            "/api/v1/oms/algo/start",
            json={"algo_type": "TWAP", "symbol": "AAPL", "side": "BUY", "target_qty": 100, "duration_minutes": 30},
        )
        assert resp.status_code == 500

    @patch("backend.routers.oms.algo_engine")
    def test_pause_algo_success(self, mock_engine):
        mock_engine.pause_algo = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/algo/algo-1/pause")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "已暂停" in data["message"]

    @patch("backend.routers.oms.algo_engine")
    def test_pause_algo_not_found(self, mock_engine):
        mock_engine.pause_algo = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/algo/algo-1/pause")
        assert resp.status_code == 400

    @patch("backend.routers.oms.algo_engine")
    def test_resume_algo_success(self, mock_engine):
        mock_engine.resume_algo = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/algo/algo-1/resume")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "已恢复" in data["message"]

    @patch("backend.routers.oms.algo_engine")
    def test_resume_algo_not_found(self, mock_engine):
        mock_engine.resume_algo = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/algo/algo-1/resume")
        assert resp.status_code == 400

    @patch("backend.routers.oms.algo_engine")
    def test_cancel_algo_success(self, mock_engine):
        mock_engine.cancel_algo = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/algo/algo-1/cancel")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "已取消" in data["message"]

    @patch("backend.routers.oms.algo_engine")
    def test_cancel_algo_not_found(self, mock_engine):
        mock_engine.cancel_algo = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post("/api/v1/oms/algo/algo-1/cancel")
        assert resp.status_code == 400


# ==========================================
# GET /api/v1/oms/mode
# POST /api/v1/oms/mode/switch
# ==========================================
class TestOmsTradingMode:
    @patch("backend.routers.oms.redis_client")
    def test_get_mode_from_redis(self, mock_redis):
        mock_redis.get = AsyncMock(return_value="LIVE")
        client = TestClient(app)
        resp = client.get("/api/v1/oms/mode")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"]["mode"] == "LIVE"

    @patch("backend.routers.oms.redis_client")
    def test_get_mode_fallback_env(self, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        client = TestClient(app)
        resp = client.get("/api/v1/oms/mode")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"]["mode"] in ("SANDBOX", "LIVE")

    @patch("backend.routers.oms.log_audit")
    @patch("backend.routers.oms.redis_client")
    def test_switch_mode_success(self, mock_redis, mock_audit):
        mock_redis.get = AsyncMock(return_value="SANDBOX")
        mock_redis.set = AsyncMock()
        mock_redis.publish = AsyncMock()

        with patch("backend.routers.oms.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            client = TestClient(app)
            resp = client.post("/api/v1/oms/mode/switch", json={"mode": "LIVE"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"]["mode"] == "LIVE"
        assert data["data"]["previous"] == "SANDBOX"

    @patch("backend.routers.oms.log_audit")
    @patch("backend.routers.oms.redis_client")
    def test_switch_mode_to_paper(self, mock_redis, mock_audit):
        mock_redis.get = AsyncMock(return_value="SANDBOX")
        mock_redis.set = AsyncMock()
        mock_redis.publish = AsyncMock()

        with patch("backend.routers.oms.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            client = TestClient(app)
            resp = client.post("/api/v1/oms/mode/switch", json={"mode": "PAPER"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"]["mode"] == "PAPER"
        assert data["data"]["previous"] == "SANDBOX"

    @patch("backend.routers.oms.redis_client")
    def test_switch_mode_invalid(self, mock_redis):
        client = TestClient(app)
        resp = client.post("/api/v1/oms/mode/switch", json={"mode": "INVALID"})
        assert resp.status_code in (400, 422)


# ==========================================
# GET /api/v1/oms/positions
# ==========================================
class TestOmsPositions:
    @patch("backend.routers.oms.oms_service")
    def test_get_positions_success(self, mock_oms):
        mock_oms.get_cached_positions = AsyncMock(return_value=[{"symbol": "00700.HK", "qty": 100}])
        client = TestClient(app)
        resp = client.get("/api/v1/oms/positions?market=HK")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 1

    @patch("backend.routers.oms.oms_service")
    def test_get_positions_empty(self, mock_oms):
        mock_oms.get_cached_positions = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.get("/api/v1/oms/positions")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"] == []
