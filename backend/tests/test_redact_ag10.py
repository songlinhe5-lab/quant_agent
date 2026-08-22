"""
AGENT-10 · 密钥脱敏层测试

验收（TODO-AGENT-ARCH.md）：
- 注入含密钥的工具入参 / 异常栈，日志与 SSE 输出中均不出现明文
- 子进程环境擦洗 drop *KEY* / *SECRET* / *TOKEN* / *PASSWORD*
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("LLM_BASE_URL", "https://api.test.com")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── redact_text 文本脱敏 ────────────────────────────────────────────


class TestRedactText:
    def test_bearer_token_redacted(self):
        from hermes_agent.redact import MASK, redact_text

        out = redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc")
        assert "eyJhbGci" not in out
        assert MASK in out

    def test_sk_style_key_redacted(self):
        from hermes_agent.redact import redact_text

        out = redact_text("调用失败，key=sk-1234567890abcdef1234567890abcdef 已过期")
        assert "sk-1234567890abcdef" not in out

    def test_url_embedded_password_redacted(self):
        from hermes_agent.redact import MASK, redact_text

        out = redact_text("redis://user:quant_redis_secret_2026@localhost:6379 连接失败")
        assert "quant_redis_secret_2026" not in out
        assert MASK in out
        assert "localhost:6379" in out  # 主机信息保留

    def test_key_value_assignment_redacted(self):
        from hermes_agent.redact import redact_text

        out = redact_text("env: FUTU_TRD_UNLOCK_PWD=abc12345 loaded")
        assert "abc12345" not in out

    def test_plain_text_untouched(self):
        from hermes_agent.redact import redact_text

        text = "AAPL 最新价 150.2，MACD 金叉，建议持仓观望。"
        assert redact_text(text) == text

    def test_non_string_passthrough(self):
        from hermes_agent.redact import redact_text

        assert redact_text(None) is None
        assert redact_text("") == ""


# ─── redact_obj 递归脱敏 ─────────────────────────────────────────────


class TestRedactObj:
    def test_sensitive_keys_masked(self):
        from hermes_agent.redact import MASK, redact_obj

        data = {"api_key": "sk-secret", "FUTU_TRD_UNLOCK_PWD": "888888", "symbol": "AAPL"}
        out = redact_obj(data)
        assert out["api_key"] == MASK
        assert out["FUTU_TRD_UNLOCK_PWD"] == MASK
        assert out["symbol"] == "AAPL"  # 业务字段不受影响

    def test_nested_structure_masked(self):
        from hermes_agent.redact import MASK, redact_obj

        data = {"config": {"headers": {"Authorization": "Bearer xyz123"}}, "items": [{"password": "p"}]}
        out = redact_obj(data)
        assert out["config"]["headers"]["Authorization"] == MASK
        assert out["items"][0]["password"] == MASK

    def test_string_values_text_redacted(self):
        from hermes_agent.redact import redact_obj

        out = redact_obj({"msg": "连接 redis://u:hunter2@host 失败"})
        assert "hunter2" not in out["msg"]

    def test_numbers_and_bools_preserved(self):
        from hermes_agent.redact import redact_obj

        out = redact_obj({"price": 150.2, "active": True, "count": 3})
        assert out == {"price": 150.2, "active": True, "count": 3}

    def test_deep_nesting_capped(self):
        """病态嵌套不导致栈溢出，超深度返回 MASK"""
        from hermes_agent.redact import redact_obj

        data: dict = {}
        cur = data
        for i in range(30):
            cur["next"] = {}
            cur = cur["next"]
        cur["leaf"] = "x"
        out = redact_obj(data)  # 不抛异常即通过
        assert out is not None


# ─── is_sensitive_key 键名识别 ────────────────────────────────────────


class TestSensitiveKeyDetection:
    def test_sensitive_keys(self):
        from hermes_agent.redact import is_sensitive_key

        assert is_sensitive_key("LLM_API_KEY")
        assert is_sensitive_key("REDIS_PASSWORD")
        assert is_sensitive_key("FUTU_TRD_UNLOCK_PWD")
        assert is_sensitive_key("access_token")
        assert is_sensitive_key("client_secret")
        assert is_sensitive_key("Authorization")

    def test_safe_keys_not_flagged(self):
        from hermes_agent.redact import is_sensitive_key

        assert not is_sensitive_key("symbol")
        assert not is_sensitive_key("keywords")  # 白名单
        assert not is_sensitive_key("monkey")  # 白名单
        assert not is_sensitive_key("session_id")


# ─── scrub_subprocess_env 子进程环境擦洗 ─────────────────────────────


class TestScrubSubprocessEnv:
    def test_drops_sensitive_env_vars(self):
        from hermes_agent.redact import scrub_subprocess_env

        env = {
            "PATH": "/usr/bin",
            "LLM_API_KEY": "sk-secret",
            "REDIS_PASSWORD": "pwd",
            "FUTU_TRD_UNLOCK_PWD": "888888",
            "QUANT_ENV": "development",
            "AUTH_TOKEN": "tok",
        }
        scrubbed = scrub_subprocess_env(env)
        assert scrubbed["PATH"] == "/usr/bin"
        assert scrubbed["QUANT_ENV"] == "development"
        assert "LLM_API_KEY" not in scrubbed
        assert "REDIS_PASSWORD" not in scrubbed
        assert "FUTU_TRD_UNLOCK_PWD" not in scrubbed
        assert "AUTH_TOKEN" not in scrubbed

    def test_does_not_mutate_source(self):
        from hermes_agent.redact import scrub_subprocess_env

        env = {"PATH": "/usr/bin", "SECRET": "x"}
        scrub_subprocess_env(env)
        assert "SECRET" in env  # 源 dict 不被修改


# ─── 集成验收：含密钥的工具异常不得泄漏明文 ──────────────────────────


class TestIntegrationRedaction:
    def test_redact_exception_message(self):
        from hermes_agent.redact import redact_exception

        try:
            raise ConnectionError("认证失败 api_key=sk-1234567890abcdef1234，请检查配置")
        except ConnectionError as e:
            msg = redact_exception(e)
        assert "sk-1234567890abcdef" not in msg
        assert "ConnectionError" in msg

    def test_tool_exception_message_redacted(self):
        """core_tool_execute 异常路径：返回的 error message 不含凭据明文"""
        import asyncio

        from hermes_agent.middleware import ToolContext, core_tool_execute

        class BrokenTool:
            name = "broken_tool"
            description = "test"

            async def run(self, **kwargs):
                raise RuntimeError("连接 redis://admin:quant_redis_secret_2026@db:6379 超时")

        ctx = ToolContext(tool_name="broken_tool", kwargs={})
        result = asyncio.run(core_tool_execute(ctx, {"broken_tool": BrokenTool()}))
        assert result["status"] == "error"
        assert "quant_redis_secret_2026" not in result["message"]
        assert "***REDACTED***" in result["message"]
