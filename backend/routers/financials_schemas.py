"""
FIN-04 · 财报看板响应装配与入参模型

路由只校验转发（AGENTS §4），因此「错误码 → 统一响应体」的翻译也放这里，
`routers/financials.py` 保持薄。错误码语义见 docs/28 §六。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

BASIS_PATTERN = "^(as_reported|latest)$"

# docs/28 §六 错误码 → 默认 HTTP 状态（异常自带 status_code 时以异常为准：
# 同一个 `fin_source_degraded` 限流该 429、源不可用该 502，客户端退避依据就是这个码）
ERROR_STATUS = {
    "fin_entity_not_found": 404,
    "fin_no_xbrl_coverage": 404,
    "fin_not_found": 404,
    "fin_job_not_found": 404,
    "fin_peer_sample_too_small": 422,
    "fin_source_degraded": 502,
    "fin_bad_request": 400,
    "fin_backfill_failed": 502,
    "fin_not_implemented": 501,
}


def ok_envelope(data: Any, message: str = "ok") -> dict[str, Any]:
    return {
        "status": "success",
        "message": message,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def err_envelope(code: str, message: str, status_code: int | None = None) -> JSONResponse:
    """错误也走统一 `{status,message,data,timestamp}`，另带 `error_code`（AGENTS §4）。"""
    payload = ok_envelope(None, message)
    payload["status"] = "error"
    payload["error_code"] = code
    return JSONResponse(status_code=status_code or ERROR_STATUS.get(code, 400), content=payload)


class BackfillRequest(BaseModel):
    """回填入参。默认后台执行，只回 job_id（禁止在请求里等采集）。"""

    entity: str = Field(..., min_length=1, description="ticker / US:CIK… / HK:00700 / CN:600519")
    source: Literal["sec"] = Field("sec", description="一手源；港A 数字层暂走 Futu/Tushare（docs/28 §1.2）")

    @field_validator("entity")
    @classmethod
    def _entity_not_blank(cls, value: str) -> str:
        """纯空格也得挡在门口：否则一路带到实体解析，404 与 400 混为一谈。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("entity 不能为空")
        return stripped


class BackfillBatchRequest(BaseModel):
    """FIN-09 批量回填入参：目标池实体清单（单批 ≤50，防打爆一手源限流）。"""

    entities: list[str] = Field(..., min_length=1, max_length=50, description="实体清单（ticker / US:CIK… / HK / CN）")
    source: Literal["sec"] = Field("sec", description="一手源；港A 数字层暂走 Futu/Tushare（docs/28 §1.2）")
