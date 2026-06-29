"""
核心工具层单元测试
覆盖: utils, response, exceptions, error_codes, encryption, config, database, retry_utils
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest


# ─── core/utils.py ──────────────────────────────────────────────────
class TestSafeFloat:
    def test_normal_values(self):
        from backend.core.utils import safe_float

        assert safe_float(3.14) == 3.14
        assert safe_float("42") == 42.0
        assert safe_float(100) == 100.0

    def test_none_returns_default(self):
        from backend.core.utils import safe_float

        assert safe_float(None) == 0.0
        assert safe_float(None, default=99.0) == 99.0

    def test_invalid_string_returns_default(self):
        from backend.core.utils import safe_float

        assert safe_float("not_a_number") == 0.0
        assert safe_float("", default=-1.0) == -1.0

    def test_list_returns_default(self):
        from backend.core.utils import safe_float

        assert safe_float([1, 2]) == 0.0


class TestSafeDivide:
    def test_normal_division(self):
        from backend.core.utils import safe_divide

        assert safe_divide(10, 2) == 5.0
        assert safe_divide(7, 3) == pytest.approx(2.333, rel=1e-2)

    def test_zero_denominator(self):
        from backend.core.utils import safe_divide

        assert safe_divide(10, 0) == 0.0
        assert safe_divide(10, 0, default=-1.0) == -1.0

    def test_string_inputs(self):
        from backend.core.utils import safe_divide

        assert safe_divide("10", "2") == 5.0

    def test_invalid_inputs(self):
        from backend.core.utils import safe_divide

        assert safe_divide(None, 5) == 0.0
        assert safe_divide("abc", 5) == 0.0


class TestSafeTruncate:
    def test_short_text_unchanged(self):
        from backend.core.utils import safe_truncate

        assert safe_truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        from backend.core.utils import safe_truncate

        text = "a" * 200
        result = safe_truncate(text, 100)
        assert len(result) <= len(text)
        assert "..." in result or len(result) <= 101

    def test_truncate_at_newline(self):
        from backend.core.utils import safe_truncate

        text = "first paragraph\n\nsecond paragraph " * 10
        result = safe_truncate(text, 50)
        assert "..." in result

    def test_non_string_input(self):
        from backend.core.utils import safe_truncate

        assert safe_truncate(123, 100) == "123"


class TestIsMyShard:
    def test_single_worker(self):
        from backend.core.utils import is_my_shard

        os.environ["WORKER_TOTAL"] = "1"
        os.environ["WORKER_ID"] = "0"
        assert is_my_shard("AAPL") is True

    def test_multi_worker(self):
        from backend.core.utils import is_my_shard

        os.environ["WORKER_TOTAL"] = "4"
        os.environ["WORKER_ID"] = "0"
        # Should deterministically return True or False
        result = is_my_shard("AAPL")
        assert isinstance(result, bool)
        # Clean up
        os.environ.pop("WORKER_TOTAL", None)
        os.environ.pop("WORKER_ID", None)


# ─── core/response.py ───────────────────────────────────────────────
class TestResponseHelpers:
    def test_success_response(self):
        from backend.core.response import success

        result = success(data={"price": 100})
        assert result["code"] == 0
        assert result["msg"] == "ok"
        assert result["data"]["price"] == 100
        assert "ts" in result

    def test_success_custom_msg(self):
        from backend.core.response import success

        result = success(msg="all good")
        assert result["msg"] == "all good"

    def test_error_response(self):
        from backend.core.error_codes import ErrorCode
        from backend.core.response import error

        resp = error(code=ErrorCode.VALIDATION_FAILED, msg="bad input")
        assert resp.status_code == 400
        import json

        body = json.loads(resp.body)
        assert body["code"] == 2001
        assert body["msg"] == "bad input"

    def test_error_with_trace_id(self):
        from backend.core.response import error

        resp = error(msg="oops", trace_id="abc-123")
        import json

        body = json.loads(resp.body)
        assert body["trace_id"] == "abc-123"

    def test_error_default_values(self):
        from backend.core.response import error

        resp = error()
        assert resp.status_code == 500


# ─── core/exceptions.py ─────────────────────────────────────────────
class TestExceptions:
    def test_base_exception(self):
        from backend.core.error_codes import ErrorCode
        from backend.core.exceptions import QuantBaseException

        exc = QuantBaseException(code=ErrorCode.INTERNAL_ERROR, msg="test error")
        assert exc.code == 5000
        assert exc.msg == "test error"
        assert str(exc) == "test error"

    def test_auth_exceptions(self):
        from backend.core.error_codes import ErrorCode
        from backend.core.exceptions import (
            AuthMissingError,
            HmacInvalidError,
            PermissionDeniedError,
            TokenExpiredError,
            TokenInvalidError,
        )

        assert AuthMissingError().code == ErrorCode.TOKEN_MISSING
        assert TokenExpiredError().code == ErrorCode.TOKEN_EXPIRED
        assert TokenInvalidError().code == ErrorCode.TOKEN_INVALID
        assert PermissionDeniedError().code == ErrorCode.PERMISSION_DENIED
        assert HmacInvalidError().code == ErrorCode.HMAC_INVALID

    def test_request_exceptions(self):
        from backend.core.error_codes import ErrorCode
        from backend.core.exceptions import ResourceNotFoundError, ValidationError

        assert ValidationError().code == ErrorCode.VALIDATION_FAILED
        assert ResourceNotFoundError().code == ErrorCode.RESOURCE_NOT_FOUND

    def test_infra_exceptions(self):
        from backend.core.error_codes import ErrorCode
        from backend.core.exceptions import (
            CircuitBreakerOpenError,
            FutuDisconnectedError,
            RedisUnavailableError,
        )

        assert FutuDisconnectedError().code == ErrorCode.FUTU_DISCONNECTED
        assert RedisUnavailableError().code == ErrorCode.REDIS_UNAVAILABLE
        assert CircuitBreakerOpenError().code == ErrorCode.CIRCUIT_BREAKER_OPEN

    def test_exception_with_trace_id(self):
        from backend.core.exceptions import AuthMissingError

        exc = AuthMissingError(trace_id="trace-abc")
        assert exc.trace_id == "trace-abc"

    def test_exception_with_data(self):
        from backend.core.exceptions import ValidationError

        exc = ValidationError(data={"field": "symbol"})
        assert exc.data == {"field": "symbol"}


# ─── core/error_codes.py ────────────────────────────────────────────
class TestErrorCodes:
    def test_error_code_values(self):
        from backend.core.error_codes import ErrorCode

        assert ErrorCode.OK == 0
        assert ErrorCode.TOKEN_MISSING == 1001
        assert ErrorCode.INTERNAL_ERROR == 5000

    def test_http_status_mapping(self):
        from backend.core.error_codes import ERROR_CODE_TO_HTTP_STATUS, ErrorCode

        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.OK] == 200
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.TOKEN_MISSING] == 401
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.VALIDATION_FAILED] == 400
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.RESOURCE_NOT_FOUND] == 404
        assert ERROR_CODE_TO_HTTP_STATUS[ErrorCode.INTERNAL_ERROR] == 500


# ─── core/encryption.py ─────────────────────────────────────────────
class TestEncryptionAdvanced:
    def test_encrypt_bytes_input(self):
        from backend.core.encryption import decrypt_sensitive_data, encrypt_sensitive_data

        plaintext_bytes = b"binary-secret-data"
        encrypted = encrypt_sensitive_data(plaintext_bytes)
        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == "binary-secret-data"

    def test_encrypt_none_returns_none(self):
        from backend.core.encryption import decrypt_sensitive_data, encrypt_sensitive_data

        assert encrypt_sensitive_data(None) is None
        assert decrypt_sensitive_data(None) is None

    def test_decrypt_invalid_data_raises(self):
        from backend.core.encryption import decrypt_sensitive_data

        with pytest.raises(ValueError):
            decrypt_sensitive_data("not-valid-base64!!!")

    def test_generate_master_key(self):
        from backend.core.encryption import generate_new_master_key

        key = generate_new_master_key()
        assert len(key) == 64  # 32 bytes hex = 64 chars

    def test_get_encryption_key_dev_fallback(self):
        from backend.core.encryption import get_encryption_key

        key = get_encryption_key()
        assert len(key) == 32


# ─── core/config.py ─────────────────────────────────────────────────
class TestConfig:
    def test_settings_loaded(self):
        from backend.core.config import settings

        assert settings is not None
        assert hasattr(settings, "database_url")

    def test_is_development(self):
        from backend.core.config import settings

        # In test env, should be testing or development
        assert settings.quant_env in ("testing", "development")

    def test_default_values(self):
        from backend.core.config import Settings

        s = Settings(
            _env_file=None,
            DATABASE_URL="sqlite:///./test.db",
            EMBEDDING_API_KEY="test",
            EMBEDDING_BASE_URL="http://test",
        )
        assert s.redis_host == "localhost"
        assert s.redis_port == 6379
        assert s.futu_port == 11111
        assert s.real_trade_execute is False

    def test_validate_empty_database_url(self):
        from pydantic import ValidationError

        from backend.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, DATABASE_URL="", EMBEDDING_API_KEY="test", EMBEDDING_BASE_URL="http://test")

    def test_validate_invalid_db_prefix(self):
        from pydantic import ValidationError

        from backend.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                DATABASE_URL="mysql://localhost/db",
                EMBEDDING_API_KEY="test",
                EMBEDDING_BASE_URL="http://test",
            )


# ─── core/database.py ───────────────────────────────────────────────
class TestDatabase:
    def test_engine_created(self):
        from backend.core.database import engine

        assert engine is not None

    def test_session_local(self):
        from backend.core.database import SessionLocal

        db = SessionLocal()
        assert db is not None
        db.close()

    def test_base_metadata(self):
        from backend.core.database import Base

        assert Base is not None
        assert Base.metadata is not None

    def test_get_db_generator(self):
        from backend.core.database import get_db

        gen = get_db()
        db = next(gen)
        assert db is not None
        db.close()


# ─── core/retry_utils.py ────────────────────────────────────────────
class TestRetryUtils:
    def test_is_retryable_rate_limit(self):
        from backend.core.retry_utils import is_retryable_http_error

        assert is_retryable_http_error(Exception("429 Too Many Requests")) is True
        assert is_retryable_http_error(Exception("rate limit exceeded")) is True
        assert is_retryable_http_error(Exception("403 forbidden")) is True

    def test_is_retryable_futu_errors(self):
        from backend.core.retry_utils import is_retryable_http_error

        assert is_retryable_http_error(Exception("频繁请求")) is True
        assert is_retryable_http_error(Exception("frequency limit")) is True
        assert is_retryable_http_error(Exception("10041 error")) is True
        assert is_retryable_http_error(Exception("connection timeout")) is True

    def test_is_not_retryable(self):
        from backend.core.retry_utils import is_retryable_http_error

        assert is_retryable_http_error(Exception("normal error")) is False
        assert is_retryable_http_error(ValueError("bad value")) is False

    def test_is_retryable_httpx_errors(self):
        import httpx

        from backend.core.retry_utils import is_retryable_http_error

        req_err = httpx.ConnectError("connection failed")
        assert is_retryable_http_error(req_err) is True

    def test_log_retry_hook(self):
        from unittest.mock import MagicMock

        from backend.core.retry_utils import log_retry_attempt

        state = MagicMock()
        state.outcome.exception.return_value = Exception("test")
        state.attempt_number = 2
        # Should not raise
        log_retry_attempt(state)
