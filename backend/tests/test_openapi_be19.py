"""BE-19: OpenAPI summary/example 完整性与导出契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.openapi_schema import (
    SUCCESS_EXAMPLE,
    build_openapi_schema,
    enrich_openapi_schema,
    iter_operations,
)


@pytest.fixture(scope="module")
def openapi_schema():
    from backend.main import app

    app.openapi_schema = None
    return build_openapi_schema(app)


class TestOpenApiEnricher:
    def test_enrich_fills_missing_summary(self):
        raw = {
            "info": {"title": "t", "version": "0"},
            "paths": {
                "/api/v1/demo": {
                    "get": {
                        "description": "演示接口说明\n更多细节",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        enriched = enrich_openapi_schema(raw)
        op = enriched["paths"]["/api/v1/demo"]["get"]
        assert op["summary"] == "演示接口说明"
        assert "example" in op["responses"]["200"]["content"]["application/json"]
        assert enriched["components"]["schemas"]["ApiResponse"]["example"] == SUCCESS_EXAMPLE

    def test_enrich_uses_path_fallback(self):
        raw = {
            "info": {},
            "paths": {
                "/api/v1/foo/bar": {
                    "post": {"responses": {"200": {"description": "ok"}}},
                }
            },
        }
        op = enrich_openapi_schema(raw)["paths"]["/api/v1/foo/bar"]["post"]
        assert op["summary"]
        assert "Foo Bar" in op["summary"] or "POST" in op["summary"]


class TestOpenApiCompleteness:
    def test_all_operations_have_summary(self, openapi_schema):
        missing = [
            f"{method.upper()} {path}"
            for method, path, op in iter_operations(openapi_schema)
            if not (op.get("summary") or "").strip()
        ]
        assert not missing, f"缺少 summary: {missing[:20]}"

    def test_all_operations_have_response_example(self, openapi_schema):
        missing = []
        for method, path, op in iter_operations(openapi_schema):
            if method == "websocket":
                continue  # WS 无 JSON envelope
            responses = op.get("responses") or {}
            ok = False
            for code in ("200", "201"):
                resp = responses.get(code)
                if not isinstance(resp, dict):
                    continue
                content = resp.get("content") or {}
                app_json = content.get("application/json") or {}
                if app_json.get("example") or app_json.get("examples"):
                    ok = True
                    break
            if not ok and responses:
                # 有些端点只声明 204 / SSE
                if any(c.startswith("2") for c in responses):
                    # 若仅有非 JSON 成功码，跳过
                    has_json_2xx = False
                    for c, r in responses.items():
                        if not c.startswith("2"):
                            continue
                        if isinstance(r, dict) and "application/json" in (r.get("content") or {}):
                            has_json_2xx = True
                    if has_json_2xx:
                        missing.append(f"{method.upper()} {path}")
                else:
                    missing.append(f"{method.upper()} {path}")
            elif not responses:
                missing.append(f"{method.upper()} {path}")
        assert not missing, f"缺少 2xx JSON example: {missing[:20]}"

    def test_info_and_api_response_component(self, openapi_schema):
        assert openapi_schema["info"]["title"]
        assert openapi_schema["info"]["version"]
        assert "ApiResponse" in openapi_schema["components"]["schemas"]

    def test_health_and_chat_overrides(self, openapi_schema):
        health = openapi_schema["paths"]["/api/v1/health"]["get"]["summary"]
        assert "健康" in health
        chat = openapi_schema["paths"]["/api/v1/chat"]["post"]["summary"]
        assert "Hermes" in chat or "SSE" in chat or "对话" in chat

    def test_exported_openapi_json_exists_and_matches(self, openapi_schema):
        """若仓库已提交 docs/openapi.json，则必须与 enrich 结果一致。"""
        path = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
        if not path.exists():
            pytest.skip("docs/openapi.json 尚未导出；先运行 scripts/export_openapi.py")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        # 忽略路径顺序差异：比较 operation 数量与关键 path
        disk_ops = list(iter_operations(on_disk))
        live_ops = list(iter_operations(openapi_schema))
        assert len(disk_ops) == len(live_ops)
        assert on_disk["info"]["version"] == openapi_schema["info"]["version"]
        assert set(on_disk["paths"]) == set(openapi_schema["paths"])
