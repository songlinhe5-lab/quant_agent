"""error_codes 单元测试 — 验证枚举与 HTTP 状态码映射完整性。"""

from data_subservice._internal.error_codes import (
    ERROR_CODE_TO_HTTP_STATUS,
    ErrorCode,
)


class TestErrorCode:
    def test_all_members_present(self):
        expected = {
            "OK",
            "TOKEN_MISSING",
            "TOKEN_EXPIRED",
            "TOKEN_INVALID",
            "PERMISSION_DENIED",
            "HMAC_INVALID",
            "VALIDATION_FAILED",
            "RESOURCE_NOT_FOUND",
            "FUTU_DISCONNECTED",
            "REDIS_UNAVAILABLE",
            "CIRCUIT_BREAKER_OPEN",
            "INTERNAL_ERROR",
        }
        assert {e.name for e in ErrorCode} == expected

    def test_ok_is_zero(self):
        assert ErrorCode.OK == 0

    def test_auth_codes_map_to_401_or_403(self):
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.TOKEN_MISSING] == 401
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.TOKEN_EXPIRED] == 401
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.TOKEN_INVALID] == 401
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.PERMISSION_DENIED] == 403
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.HMAC_INVALID] == 403

    def test_validation_codes(self):
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.VALIDATION_FAILED] == 400
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.RESOURCE_NOT_FOUND] == 404

    def test_infra_codes_map_to_503(self):
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.FUTU_DISCONNECTED] == 503
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.REDIS_UNAVAILABLE] == 503
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.CIRCUIT_BREAKER_OPEN] == 503

    def test_internal_maps_to_500(self):
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.INTERNAL_ERROR] == 500

    def test_ok_maps_to_200(self):
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.OK] == 200

    def test_every_code_has_http_status(self):
        for code in ErrorCode:
            assert code.value in ERROR_CODE_TO_HTTP_STATUS
            assert 100 <= ERROR_CODE_TO_HTTP_STATUS[code.value] < 600
