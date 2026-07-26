"""
ALERT-COND-01: 自由布尔表达式求值引擎 (后端半场)
================================================

与前端 `frontend/src/features/quotes/custom-indicator/engine.ts` 的 `evaluate`
**语义 1:1 对齐**，把前端沙盒敲的自由布尔表达式（如 `RSI(14) > 70 && CLOSE > MA(CLOSE, 20)`）
直接搬进后端告警引擎，复用现有 `AlertEngine` 的订阅 / 冷却 / 多通道推送基建。

设计要点（与 TS 引擎严格一致）:
  - 结果序列按 `np.nan` 表示 null（TS 用 `null`），比较 / 逻辑运算遇 nan 返回 nan（= 未触发）。
  - 布尔真值编码为 1.0 / 假为 0.0（TS 同）。
  - 支持字段 OPEN/HIGH/LOW/CLOSE/VOLUME(VOL)；命名空间 KDJ.{K,D,J} / MACD.{DIFF,DEA,HIST} / BB.{UPPER,LOWER,MID}。
  - 支持函数 MA/SMA/EMA/RSI/REF/CROSS/HHV/LLV/ABS/SQRT/MAX/MIN 与运算符 + - * / % > < >= <= == != && || !。
  - 参数用 `@name` 引用，由 `params` 字典提供。
  - 所有指标（MA/EMA/RSI/MACD/KDJ/BOLL）的递推公式与边界处理逐行复刻 TS 实现，
    由 `backend/tests/test_expr_evaluator.py` 加载 `frontend/.../expr-golden.json`
    （由 TS 引擎生成）做跨语言单测锁死，杜绝语义漂移。

性能：纯矢量化（numpy），无 Python 级 for 遍历 K 线（仅在指标递推与 CROSS/HHV/LLV 内部必要处用 C 速循环）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.core.alert_models import AlertRule, AlertRuleType

__all__ = ["ExprError", "evaluate_expr", "ExprEvaluator"]


# ─────────────────────────────────────────
#  错误类型
# ─────────────────────────────────────────


class ExprError(Exception):
    """表达式语法 / 语义错误"""


# ─────────────────────────────────────────
#  词法 / 语法分析（递归下降，与 TS 同构）
# ─────────────────────────────────────────


_KNOWN_NS = {
    "KDJ": {"K", "D", "J"},
    "MACD": {"DIFF", "DEA", "HIST"},
    "BB": {"UPPER", "LOWER", "MID"},
}


def _tokenize(src: str) -> List[Tuple[str, Any]]:
    toks: List[Tuple[str, Any]] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\n\r":
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i + 1
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            toks.append(("num", float(src[i:j])))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            up = word.upper()
            if up == "AND":
                toks.append(("op", "&&"))
            elif up == "OR":
                toks.append(("op", "||"))
            elif up == "NOT":
                toks.append(("op", "!"))
            else:
                toks.append(("id", up))
            i = j
            continue
        if c == "@":
            j = i + 1
            if j < n and (src[j].isalnum() or src[j] == "_"):
                while j < n and (src[j].isalnum() or src[j] == "_"):
                    j += 1
                toks.append(("param", src[i + 1 : j]))
                i = j
                continue
            raise ExprError('无法识别的字符 "@"')
        two = src[i : i + 2]
        if two in (">=", "<=", "==", "!=", "&&", "||"):
            toks.append(("op", two))
            i += 2
            continue
        if c in "><+-*/%!":
            toks.append(("op", c))
            i += 1
            continue
        if c == ".":
            toks.append(("dot", None))
            i += 1
            continue
        if c == "(":
            toks.append(("lp", None))
            i += 1
            continue
        if c == ")":
            toks.append(("rp", None))
            i += 1
            continue
        if c == ",":
            toks.append(("comma", None))
            i += 1
            continue
        raise ExprError(f'无法识别的字符 "{c}" (位置 {i})')
    return toks


class _Parser:
    def __init__(self, toks: List[Tuple[str, Any]]):
        self.toks = toks
        self.p = 0

    def _peek(self):
        return self.toks[self.p] if self.p < len(self.toks) else None

    def _next(self):
        t = self.toks[self.p]
        self.p += 1
        return t

    def _expect(self, t: str):
        tk = self._next()
        if tk is None or tk[0] != t:
            raise ExprError("表达式语法错误：缺少右括号或存在多余符号")

    def parse(self):
        n = self._expr()
        if self.p < len(self.toks):
            raise ExprError("表达式语法错误：末尾存在多余符号")
        return n

    def _expr(self):
        return self._or_expr()

    def _or_expr(self):
        left = self._and_expr()
        while True:
            tk = self._peek()
            if tk and tk[0] == "op" and tk[1] == "||":
                self._next()
                right = self._and_expr()
                left = ("bin", "||", left, right)
            else:
                break
        return left

    def _and_expr(self):
        left = self._cmp_expr()
        while True:
            tk = self._peek()
            if tk and tk[0] == "op" and tk[1] == "&&":
                self._next()
                right = self._cmp_expr()
                left = ("bin", "&&", left, right)
            else:
                break
        return left

    def _cmp_expr(self):
        left = self._add_expr()
        ops = {">", "<", ">=", "<=", "==", "!="}
        while True:
            tk = self._peek()
            if tk and tk[0] == "op" and tk[1] in ops:
                op = self._next()[1]
                right = self._add_expr()
                left = ("bin", op, left, right)
            else:
                break
        return left

    def _add_expr(self):
        left = self._mul_expr()
        while True:
            tk = self._peek()
            if tk and tk[0] == "op" and tk[1] in "+-":
                op = self._next()[1]
                right = self._mul_expr()
                left = ("bin", op, left, right)
            else:
                break
        return left

    def _mul_expr(self):
        left = self._unary()
        while True:
            tk = self._peek()
            if tk and tk[0] == "op" and tk[1] in "*/%":
                op = self._next()[1]
                right = self._unary()
                left = ("bin", op, left, right)
            else:
                break
        return left

    def _unary(self):
        tk = self._peek()
        if tk and tk[0] == "op" and tk[1] in "-!":
            op = self._next()[1]
            return ("unary", op, self._unary())
        return self._primary()

    def _primary(self):
        tk = self._peek()
        if tk is None:
            raise ExprError("表达式不完整")
        if tk[0] == "num":
            self._next()
            return ("num", tk[1])
        if tk[0] == "param":
            self._next()
            return ("param", tk[1])
        if tk[0] == "lp":
            self._next()
            e = self._expr()
            self._expect("rp")
            return e
        if tk[0] == "id":
            self._next()
            if self._peek() and self._peek()[0] == "dot":
                self._next()
                f = self._next()
                if f is None or f[0] != "id":
                    raise ExprError("命名空间后应为字段名")
                return ("member", tk[1], f[1])
            if self._peek() and self._peek()[0] == "lp":
                self._next()
                args: List[Any] = []
                if not (self._peek() and self._peek()[0] == "rp"):
                    args.append(self._expr())
                    while self._peek() and self._peek()[0] == "comma":
                        self._next()
                        args.append(self._expr())
                self._expect("rp")
                return ("call", tk[1], args)
            return ("var", tk[1])
        raise ExprError(f"意外的符号 {tk}")


# ─────────────────────────────────────────
#  指标原语（逐行复刻 TS engine 的递推语义）
# ─────────────────────────────────────────


def _calc_ma(x: np.ndarray, period: int) -> np.ndarray:
    length = len(x)
    out = np.full(length, np.nan)
    s = 0.0
    for i in range(length):
        v = x[i]
        if np.isnan(v):
            s = 0.0
            continue
        s += v
        if i >= period:
            s -= x[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def _calc_ema(x: np.ndarray, period: int) -> np.ndarray:
    length = len(x)
    out = np.full(length, np.nan)
    k = 2.0 / (period + 1)
    prev = None
    for i in range(length):
        v = x[i]
        if np.isnan(v):
            continue
        prev = v if prev is None else (v - prev) * k + prev
        out[i] = prev
    return out


def _calc_rsi(x: np.ndarray, period: int) -> np.ndarray:
    length = len(x)
    out = np.full(length, np.nan)
    gains = 0.0
    losses = 0.0
    for i in range(1, length):
        v = x[i]
        pv = x[i - 1]
        if np.isnan(v) or np.isnan(pv):
            continue
        change = v - pv
        if i <= period:
            if change > 0:
                gains += change
            else:
                losses -= change
            if i == period:
                ag = gains / period
                al = losses / period
                rs = 100.0 if al == 0 else ag / al
                out[i] = 100 - 100 / (1 + rs)
        else:
            prev_rsi = out[i - 1]
            prev_avg_gain = (
                (100 / (100 - prev_rsi) - 1) * (losses / period) if not np.isnan(prev_rsi) else gains / period
            )
            prev_avg_loss = losses / period
            if change > 0:
                gains = (prev_avg_gain * (period - 1) + change) / period
                losses = (prev_avg_loss * (period - 1)) / period
            else:
                gains = (prev_avg_gain * (period - 1)) / period
                losses = (prev_avg_loss * (period - 1) - change) / period
            rs = 100.0 if losses == 0 else gains / losses
            out[i] = 100 - 100 / (1 + rs)
    return out


def _calc_macd(
    closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    length = len(closes)
    diff = np.full(length, np.nan)
    dea = np.full(length, np.nan)
    hist = np.full(length, np.nan)
    kf = 2.0 / (fast + 1)
    ks = 2.0 / (slow + 1)
    ksig = 2.0 / (signal + 1)
    fe = 0.0
    se = 0.0
    for i in range(length):
        v = closes[i]
        if np.isnan(v):
            continue
        fe = v if i == 0 else (v - fe) * kf + fe
        se = v if i == 0 else (v - se) * ks + se
        d = fe - se
        prev_dea = dea[i - 1] if i > 0 else None
        cur_dea = d if prev_dea is None else (d - prev_dea) * ksig + prev_dea
        diff[i] = d
        dea[i] = cur_dea
        hist[i] = d - cur_dea
    return diff, dea, hist


def _calc_kdj(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    p: int = 9,
    ks: int = 3,
    ds: int = 3,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    length = len(closes)
    K = np.full(length, np.nan)
    D = np.full(length, np.nan)
    J = np.full(length, np.nan)
    kk = 2.0 / ks
    dk = 2.0 / ds
    for i in range(length):
        if i < p - 1 or np.isnan(highs[i]) or np.isnan(lows[i]) or np.isnan(closes[i]):
            continue
        hh = -math.inf
        ll = math.inf
        for j in range(p):
            hh = max(hh, highs[i - j])
            ll = min(ll, lows[i - j])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        prev_k = K[i - 1] if not np.isnan(K[i - 1]) else 50.0
        prev_d = D[i - 1] if not np.isnan(D[i - 1]) else 50.0
        k = kk * prev_k + (1 - kk) * rsv
        d = dk * prev_d + (1 - dk) * k
        K[i] = k
        D[i] = d
        J[i] = 3 * k - 2 * d
    return K, D, J


def _calc_boll(x: np.ndarray, period: int = 20, mult: float = 2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    length = len(x)
    mid = np.full(length, np.nan)
    upper = np.full(length, np.nan)
    lower = np.full(length, np.nan)
    for i in range(length):
        if i < period - 1 or np.isnan(x[i]):
            continue
        s = 0.0
        for j in range(period):
            s += x[i - j]
        ma = s / period
        varc = 0.0
        for j in range(period):
            d = x[i - j] - ma
            varc += d * d
        sd = math.sqrt(varc / period)
        mid[i] = ma
        upper[i] = ma + mult * sd
        lower[i] = ma - mult * sd
    return mid, upper, lower


def _rolling_extreme(x: np.ndarray, period: int, kind: str) -> np.ndarray:
    length = len(x)
    out = np.full(length, np.nan)
    for i in range(length):
        if i < period - 1 or np.isnan(x[i]):
            continue
        acc = None
        for j in range(period):
            v = x[i - j]
            if np.isnan(v):
                acc = None
                break
            acc = v if acc is None else (max(acc, v) if kind == "max" else min(acc, v))
        out[i] = acc
    return out


# ─────────────────────────────────────────
#  求值主入口
# ─────────────────────────────────────────


def evaluate_expr(
    expr: str,
    bars: List[Dict[str, Any]],
    params: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    求值自由布尔表达式，返回与 TS `evaluate` 同构的结果：
        { ok, is_bool, values: List[float|None], error }

    - values 中 `None` 表示 null（未定义），等价于 TS 的 `null`。
    - ok=False 时 values 为空数组、error 为可读信息。
    """
    try:
        toks = _tokenize(expr)
        ast = _Parser(toks).parse()
    except ExprError as e:
        return {"ok": False, "is_bool": False, "values": [], "error": str(e)}

    length = len(bars)
    if length == 0:
        return {"ok": False, "is_bool": False, "values": [], "error": "无 K 线数据"}

    closes = np.array([float(b.get("close", np.nan)) for b in bars], dtype=float)
    highs = np.array([float(b.get("high", np.nan)) for b in bars], dtype=float)
    lows = np.array([float(b.get("low", np.nan)) for b in bars], dtype=float)
    opens = np.array([float(b.get("open", np.nan)) for b in bars], dtype=float)
    vols = np.array([float(b.get("volume", np.nan)) for b in bars], dtype=float)

    kdj = _calc_kdj(highs, lows, closes)
    macd = _calc_macd(closes, 12, 26, 9)
    boll = _calc_boll(closes, 20, 2)

    def _get_const(node: Any, what: str) -> int:
        v = _eval_node(node)
        arr = v["arr"]
        if np.any(np.isnan(arr)):
            raise ExprError(f"{what} 参数含无效值")
        if v["is_bool"]:
            raise ExprError(f"{what} 必须是常量数字")
        first = float(arr[0])
        if not (float(first).is_integer() and first > 0):
            raise ExprError(f"{what} 必须是正整数")
        return int(first)

    def _eval_node(node: Any) -> Dict[str, Any]:
        k = node[0]
        if k == "num":
            return {"arr": np.full(length, float(node[1])), "is_bool": False}
        if k == "param":
            val = params.get(node[1]) if params else None
            if val is None or not isinstance(val, (int, float)) or float(val) != float(val):
                raise ExprError(f"参数 @{node[1]} 未提供")
            return {"arr": np.full(length, float(val)), "is_bool": False}
        if k == "var":
            m = {
                "OPEN": opens,
                "HIGH": highs,
                "LOW": lows,
                "CLOSE": closes,
                "VOLUME": vols,
                "VOL": vols,
            }
            s = m.get(node[1])
            if s is None:
                raise ExprError(f'未知字段 "{node[1]}"')
            return {"arr": s.copy(), "is_bool": False}
        if k == "member":
            ns = node[1]
            fld = node[2]
            if ns == "KDJ":
                idx = {"K": 0, "D": 1, "J": 2}.get(fld)
                if idx is None:
                    raise ExprError(f'未知 KDJ 字段 "{fld}"')
                return {"arr": kdj[idx].copy(), "is_bool": False}
            if ns == "MACD":
                idx = {"DIFF": 0, "DEA": 1, "HIST": 2}.get(fld.upper())
                if idx is None:
                    raise ExprError(f'未知 MACD 字段 "{fld}"')
                return {"arr": macd[idx].copy(), "is_bool": False}
            if ns == "BB":
                idx = {"UPPER": 1, "LOWER": 2, "MID": 0}.get(fld.upper())
                if idx is None:
                    raise ExprError(f'未知 BB 字段 "{fld}"')
                return {"arr": boll[idx].copy(), "is_bool": False}
            raise ExprError(f'未知命名空间 "{ns}"')
        if k == "unary":
            e = _eval_node(node[2])
            arr = e["arr"]
            if node[1] == "-":
                return {"arr": np.where(np.isnan(arr), np.nan, -arr), "is_bool": False}
            out = np.full(length, np.nan)
            m = ~np.isnan(arr)
            out[m] = np.where(arr[m] != 0, 0.0, 1.0)
            return {"arr": out, "is_bool": True}
        if k == "bin":
            op = node[1]
            l = _eval_node(node[2])
            r = _eval_node(node[3])
            la = l["arr"]
            ra = r["arr"]
            if op in (">", "<", ">=", "<=", "==", "!="):
                out = np.full(length, np.nan)
                m = ~(np.isnan(la) | np.isnan(ra))
                av = la[m]
                bv = ra[m]
                if op == ">":
                    res = av > bv
                elif op == "<":
                    res = av < bv
                elif op == ">=":
                    res = av >= bv
                elif op == "<=":
                    res = av <= bv
                elif op == "==":
                    res = av == bv
                else:
                    res = av != bv
                out[m] = np.where(res, 1.0, 0.0)
                return {"arr": out, "is_bool": True}
            if op in ("&&", "||"):
                out = np.full(length, np.nan)
                m = ~(np.isnan(la) | np.isnan(ra))
                av = la[m] != 0
                bv = ra[m] != 0
                res = (av & bv) if op == "&&" else (av | bv)
                out[m] = np.where(res, 1.0, 0.0)
                return {"arr": out, "is_bool": True}
            # 算术
            out = np.full(length, np.nan)
            m = ~(np.isnan(la) | np.isnan(ra))
            av = la[m]
            bv = ra[m]
            if op == "+":
                res = av + bv
            elif op == "-":
                res = av - bv
            elif op == "*":
                res = av * bv
            elif op == "/":
                res = np.where(bv == 0, np.nan, av / bv)
            else:  # %
                res = np.where(bv == 0, np.nan, av % bv)
            out[m] = res
            return {"arr": out, "is_bool": False}
        if k == "call":
            name = node[1]
            args = node[2]
            req2 = {"REF", "HHV", "LLV", "CROSS", "MAX", "MIN"}
            req1 = {"ABS", "SQRT"}
            if name in req2 and len(args) < 2:
                raise ExprError(f"函数 {name}() 需要 2 个参数")
            if name in req1 and len(args) < 1:
                raise ExprError(f"函数 {name}() 需要 1 个参数")
            if name in ("MA", "SMA", "EMA", "RSI") and len(args) not in (1, 2):
                raise ExprError(f"函数 {name}() 需要 1 或 2 个参数")
            if name in ("MA", "SMA", "EMA", "RSI"):
                single = len(args) == 1
                src = closes.copy() if single else _eval_node(args[0])["arr"]
                period = _get_const(args[0] if single else args[1], f"{name} 周期")
                if name in ("MA", "SMA"):
                    return {"arr": _calc_ma(src, period), "is_bool": False}
                if name == "EMA":
                    return {"arr": _calc_ema(src, period), "is_bool": False}
                return {"arr": _calc_rsi(src, period), "is_bool": False}
            if name == "REF":
                nn = _get_const(args[1], "REF 周期")
                x = _eval_node(args[0])["arr"]
                out = np.full(length, np.nan)
                out[nn:] = x[: length - nn]
                return {"arr": out, "is_bool": False}
            if name in ("HHV", "LLV"):
                x = _eval_node(args[0])["arr"]
                period = _get_const(args[1], f"{name} 周期")
                return {
                    "arr": _rolling_extreme(x, period, "max" if name == "HHV" else "min"),
                    "is_bool": False,
                }
            if name == "CROSS":
                a = _eval_node(args[0])["arr"]
                b = _eval_node(args[1])["arr"]
                out = np.full(length, np.nan)
                for i in range(1, length):
                    a0 = a[i - 1]
                    b0 = b[i - 1]
                    a1 = a[i]
                    b1 = b[i]
                    if np.isnan(a0) or np.isnan(b0) or np.isnan(a1) or np.isnan(b1):
                        continue
                    out[i] = 1.0 if (a0 <= b0 and a1 > b1) else 0.0
                return {"arr": out, "is_bool": True}
            if name == "ABS":
                x = _eval_node(args[0])["arr"]
                return {"arr": np.where(np.isnan(x), np.nan, np.abs(x)), "is_bool": False}
            if name == "SQRT":
                x = _eval_node(args[0])["arr"]
                out = np.full(length, np.nan)
                m = ~np.isnan(x)
                out[m] = np.where(x[m] < 0, np.nan, np.sqrt(x[m]))
                return {"arr": out, "is_bool": False}
            if name in ("MAX", "MIN"):
                a = _eval_node(args[0])["arr"]
                b = _eval_node(args[1])["arr"]
                out = np.full(length, np.nan)
                mm = ~(np.isnan(a) | np.isnan(b))
                out[mm] = np.maximum(a[mm], b[mm]) if name == "MAX" else np.minimum(a[mm], b[mm])
                return {"arr": out, "is_bool": False}
            raise ExprError(f'未知函数 "{name}()"')
        raise ExprError("表达式解析失败")

    try:
        res = _eval_node(ast)
        raw = res["arr"].tolist()
        values = [None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v) for v in raw]
        return {"ok": True, "is_bool": bool(res["is_bool"]), "values": values, "error": None}
    except ExprError as e:
        return {"ok": False, "is_bool": False, "values": [], "error": str(e)}


# ─────────────────────────────────────────
#  轮询缓冲 + 规则评估（挂到 AlertEngine）
# ─────────────────────────────────────────


class ExprEvaluator:
    """
    维护每个标的的滚动 K 线缓冲（来自行情流），并针对 EXPR 类型规则求值。

    设计：行情流通常只给 close/volume，前端沙盒同源；为兼容 MA/RSI 等需序列的指标，
    引擎把每次行情累积成滚动 bar 序列（open=high=low=close=price 的退化 bar 仅影响
    依赖 OHLC 的 KDJ/BOLL 精度，对纯 close 类指标无影响）。真实 OHLCV 由
    `get_tech_indicators` 路径补齐时精度更高。
    """

    def __init__(self, window: int = 500):
        self._window = window
        self._bars: Dict[str, List[Dict[str, Any]]] = {}

    def feed(self, ticker: str, bar: Dict[str, Any]) -> None:
        lst = self._bars.setdefault(ticker, [])
        if lst and lst[-1].get("time") == bar.get("time"):
            last = lst[-1]
            last["high"] = max(last["high"], bar["high"])
            last["low"] = min(last["low"], bar["low"])
            last["close"] = bar["close"]
            last["volume"] = bar["volume"]
        else:
            lst.append(
                {
                    "time": bar.get("time"),
                    "open": bar.get("open"),
                    "high": bar.get("high"),
                    "low": bar.get("low"),
                    "close": bar.get("close"),
                    "volume": bar.get("volume"),
                }
            )
            if len(lst) > self._window:
                lst.pop(0)

    def get_bars(self, ticker: str) -> List[Dict[str, Any]]:
        return self._bars.get(ticker, [])

    def evaluate(
        self, ticker: str, expr: str, params: Optional[Dict[str, float]] = None
    ) -> Tuple[bool, bool, List[Optional[float]]]:
        """基于已缓冲的行情对表达式求值，等价于模块级 evaluate_expr。"""
        bars = self.get_bars(ticker)
        r = evaluate_expr(expr, bars, params or {})
        return (r["ok"], r["is_bool"], r["values"])

    def evaluate_rule(self, rule: AlertRule) -> Tuple[bool, Optional[float]]:
        """返回 (是否当前命中, 末根收盘价)。

        仅当结果为布尔序列且末根有效值 == 1.0 视为命中；命中时以末根收盘价作为
        可读 trigger_value 供告警事件展示，否则返回 None。
        """
        if rule.rule_type != AlertRuleType.EXPR:
            return (False, None)
        expr = rule.metadata.get("expr")
        if not expr:
            return (False, None)
        params = rule.metadata.get("expr_params") or {}
        bars = self.get_bars(rule.ticker)
        if len(bars) < 2:
            return (False, None)
        r = evaluate_expr(expr, bars, params)
        if not r["ok"] or not r["is_bool"]:
            return (False, None)
        last = None
        for v in reversed(r["values"]):
            if v is not None:
                last = v
                break
        if last is None or last != 1.0:
            return (False, None)
        tv = float(bars[-1].get("close")) if bars else None
        return (True, tv)
