"""
Chat 路由单元测试
覆盖: backend/routers/chat.py

注：chat_router 未在 main.py 中 include，故在此单独构造 FastAPI app。
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.chat import router as chat_router


def _build_app() -> FastAPI:
    """构建挂载 chat_router 的独立 FastAPI app"""
    app = FastAPI()
    app.include_router(chat_router)
    return app


class TestChatRoutes:
    """Chat 多模态对话路由测试"""

    def test_chat_text_only_success(self):
        """正常路径：纯文本对话流式返回"""
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={
                "session_id": "sess-001",
                "messages": [
                    {"role": "user", "content": "你好"},
                ],
            },
        )
        assert resp.status_code == 200
        # 流式响应 NDJSON
        text = resp.text
        assert "thought_chunk" in text
        assert "text_chunk" in text

    def test_chat_with_image_attachment(self):
        """附件路径：携带图片附件构造多模态消息"""
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={
                "session_id": "sess-002",
                "messages": [
                    {
                        "role": "user",
                        "content": "识别这张图",
                        "attachments": [
                            {
                                "name": "chart.png",
                                "url": "data:image/png;base64,iVBORw0KGgo=",
                                "type": "image/png",
                            }
                        ],
                    }
                ],
            },
        )
        assert resp.status_code == 200

    def test_chat_with_pdf_attachment(self):
        """附件路径：携带 PDF 附件触发降级解析"""
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={
                "session_id": "sess-003",
                "messages": [
                    {
                        "role": "user",
                        "content": "总结此 PDF",
                        "attachments": [
                            {
                                "name": "report.pdf",
                                "url": "data:application/pdf;base64,JVBERi0xLjQ=",
                                "type": "application/pdf",
                            }
                        ],
                    }
                ],
            },
        )
        assert resp.status_code == 200

    def test_chat_invalid_payload_missing_session_id(self):
        """参数校验：缺少 session_id 返回 422"""
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 422

    def test_chat_invalid_payload_missing_messages(self):
        """参数校验：缺少 messages 返回 422"""
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={"session_id": "sess-004"},
        )
        assert resp.status_code == 422
