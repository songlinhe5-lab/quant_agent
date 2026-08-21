"""
AGENT-10 · 密钥作用域与日志脱敏

AGENTS.md 安全红线：交易系统持有 Futu 解锁密码、券商凭据、各数据源 API Key，
日志 / 遥测 / 异常消息中严禁出现明文凭据。

本模块提供三层脱敏能力（参考 hermes redact.py + dsh defensive-patterns.md）：
1. redact_text   — 正则识别常见凭据格式（Bearer / sk-xxx / URL 内嵌密码等）
2. redact_obj    — 递归脱敏 dict/list，键名命中敏感模式即替换值
3. scrub_subprocess_env — 子进程环境擦洗（AGENT-05 沙箱预置），
   drop *KEY* / *SECRET* / *TOKEN* / *PASSWORD* / *PWD* / *CREDENTIAL*
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── 脱敏占位符 ──────────────────────────────────────────────────────
MASK = "***REDACTED***"

# ── 敏感键名模式（小写匹配）─────────────────────────────────────────
SENSITIVE_KEY_PATTERNS: List[str] = [
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "pwd",
    "credential",
    "authorization",
    "auth_token",
    "unlock_pwd",
    "private",
]

# 白名单：键名含敏感词但语义非凭据（避免误伤业务字段）
_SAFE_KEY_EXACT = {
    "monkey",
    "turkey",
    "keyword",
    "keywords",
    "apikey_version",
}

# ── 文本正则：识别字符串中的常见凭据格式 ────────────────────────────
_TEXT_PATTERNS: List[re.Pattern] = [
    # Authorization: Bearer <token>
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"),
    # OpenAI / DeepSeek 风格 sk-xxx（≥16 位）
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    # URL 内嵌凭据 scheme://user:pass@host
    re.compile(r"(?i)((?:https?|redis|amqp|postgresql|mysql)://[^:/\s]+:)([^@\s]+)(@)"),
    # key= / token= / password= / secret= / pwd= 形式的赋值（env、query string、日志）
    re.compile(
        r"(?i)((?:api_?key|apikey|secret|token|password|passwd|pwd|credential|auth)"
        r"\s*[=:]\s*)([^\s'\"]{4,})"
    ),
]


def is_sensitive_key(key: str) -> bool:
    """判断键名是否为敏感凭据键。"""
    if not key:
        return False
    lk = key.lower()
    if lk in _SAFE_KEY_EXACT:
        return False
    return any(pat in lk for pat in SENSITIVE_KEY_PATTERNS)


def redact_text(text: str) -> str:
    """对文本中的常见凭据格式做脱敏（用于日志消息 / 异常栈 / SSE 诊断输出）。"""
    if not text or not isinstance(text, str):
        return text
    out = text
    for pat in _TEXT_PATTERNS:
        if pat.groups == 3:
            # URL 内嵌凭据：保留 scheme://user: 与 @，替换中间密码段
            out = pat.sub(lambda m: f"{m.group(1)}{MASK}{m.group(3)}", out)
        elif pat.groups >= 1:
            # 保留前缀组（如 "Bearer " / "api_key="），替换凭据本体
            out = pat.sub(lambda m: f"{m.group(1)}{MASK}", out)
        else:
            # 无捕获组（如 sk-xxx 裸凭据），整段替换
            out = pat.sub(MASK, out)
    return out


def redact_obj(obj: Any, _depth: int = 0) -> Any:
    """
    递归脱敏任意数据结构。

    - dict：键名命中敏感模式 → 值替换为 MASK；否则递归处理值
    - list/tuple：逐元素递归
    - str：走 redact_text
    - 其他原样返回（数值/布尔不受影响）

    深度上限 12 层，防止恶意/病态嵌套导致栈溢出。
    """
    if _depth > 12:
        return MASK
    if isinstance(obj, dict):
        return {
            k: (MASK if isinstance(k, str) and is_sensitive_key(k) else redact_obj(v, _depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v, _depth + 1) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(v, _depth + 1) for v in obj)
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def scrub_subprocess_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    子进程环境擦洗（AGENT-05 脚本沙箱预置）。

    dsh defensive-patterns.md 规则：spawn 子进程时 drop
    *KEY* / *SECRET* / *TOKEN* / *PASSWORD* / *PWD* / *CREDENTIAL*。

    Args:
        env: 源环境 dict；None 时取 os.environ 快照
    Returns:
        清洗后的新 dict（不修改源）
    """
    import os

    src = dict(os.environ) if env is None else dict(env)
    return {k: v for k, v in src.items() if not is_sensitive_key(k)}


def redact_exception(exc: BaseException) -> str:
    """将异常转为脱敏后的消息字符串（用于错误日志与 SSE 诊断字段）。"""
    return redact_text(f"{type(exc).__name__}: {exc}")
