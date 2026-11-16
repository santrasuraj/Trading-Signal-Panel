"""Your own indicators as formulas: a small, safe formula language (not code) for the chart and the scans.

    (close - sma(close, 50)) / atr(14)          distance from the 50-day average in ATRs
    rsi(close, 14) - rsi(ref(close, 5), 14)     RSI change over a week
    highest(high, 20) / lowest(low, 20) - 1     the 20-day range as a fraction

Allowed: numbers, + - * / and ** (with a number as the power), brackets, the fields open high low close volume, and
the functions below; window lengths are whole numbers from 1 to 400. Anything else (names, attributes, strings,
keyword arguments) is refused before evaluation, so a formula can only compute. The same formula runs on one stock's
columns (the chart) or on every stock at once (wide frames: the scans).

Saved formulas (data/formulas.json, at most 30) become scan fields "f_<id>" in the "Your formulas" group.
"""
from __future__ import annotations

import ast
import json
import re
import uuid

import numpy as np
import pandas as pd

from .settings import DATA_DIR

FILE = "formulas.json"
MAX_LEN = 300
MAX_DEPTH = 24
MAX_N = 400
MAX_SAVED = 30
FIELDS = ("open", "high", "low", "close", "volume")
FUNCS = {   # name: (number of series arguments, has a window, help)
    "sma": (1, True, "simple moving average: sma(close, 20)"),
    "ema": (1, True, "exponential moving average: ema(close, 21)"),
    "rsi": (1, True, "relative strength index: rsi(close, 14)"),
    "highest": (1, True, "highest value over n bars: highest(high, 20)"),
    "lowest": (1, True, "lowest value over n bars: lowest(low, 20)"),
    "ref": (1, True, "the value n bars ago: ref(close, 5)"),
    "stdev": (1, True, "standard deviation over n bars: stdev(close, 20)"),
    "sum": (1, True, "sum over n bars: sum(volume, 5)"),
    "roc": (1, True, "% change over n bars: roc(close, 10)"),
    "atr": (0, True, "average true range: atr(14)"),
    "abs": (1, False, "absolute value: abs(close - open)"),
    "log": (1, False, "natural logarithm: log(close)"),
    "sqrt": (1, False, "square root: sqrt(volume)"),
    "max": (2, False, "the larger of two: max(open, close)"),
    "min": (2, False, "the smaller of two: min(open, close)"),
}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b}


class FormulaError(ValueError):
    pass


def check(expr: str) -> ast.Expression:
    """Parse and allow only the formula language; raises FormulaError with a plain message."""
    e = (expr or "").strip()
    if not e:
        raise FormulaError("Type a formula, e.g. (close - sma(close, 50)) / atr(14).")
    if len(e) > MAX_LEN:
        raise FormulaError(f"At most {MAX_LEN} characters.")
    try:
        tree = ast.parse(e, mode="eval")
    except SyntaxError as x:
        raise FormulaError(f"Not a formula: {x.msg} (character {x.offset}).") from None

    def walk(n, depth=0):
        if depth > MAX_DEPTH:
            raise FormulaError("Too deeply nested.")
        if isinstance(n, ast.Expression):
            return walk(n.body, depth + 1)
        if isinstance(n, ast.Constant):
            if isinstance(n.value, bool) or not isinstance(n.value, (int, float)):
                raise FormulaError("Only numbers can be written as values.")
            return
        if isinstance(n, ast.Name):
            if n.id not in FIELDS:
                raise FormulaError(f"Unknown name '{n.id}': use {', '.join(FIELDS)} or a function.")
            return
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return walk(n.operand, depth + 1)
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, ast.Pow):
                if not isinstance(n.right, ast.Constant) or not isinstance(n.right.value, (int, float)) or abs(n.right.value) > 4:
                    raise FormulaError("A power must be a number between -4 and 4: x ** 2.")
                return walk(n.left, depth + 1)
            if type(n.op) not in _BIN:
                raise FormulaError("Use + - * / and ** only.")
            walk(n.left, depth + 1)
            walk(n.right, depth + 1)
            return
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in FUNCS:
                name = getattr(n.func, "id", "that")
                raise FormulaError(f"Unknown function '{name}': use {', '.join(FUNCS)}.")
            if n.keywords:
                raise FormulaError(f"{n.func.id}(): no named arguments.")
            nser, window, _ = FUNCS[n.func.id]
            want = nser + (1 if window else 0)
            if len(n.args) != want:
                raise FormulaError(f"{n.func.id}() takes {want} argument{'s' if want != 1 else ''}: {FUNCS[n.func.id][2]}.")
            for a in n.args[:nser]:
                walk(a, depth + 1)
            if window:
                w = n.args[-1]
                if not (isinstance(w, ast.Constant) and isinstance(w.value, int) and not isinstance(w.value, bool)
                        and 1 <= w.value <= MAX_N):
                    raise FormulaError(f"{n.func.id}(): the window must be a whole number from 1 to {MAX_N}.")
            return
        raise FormulaError("Only numbers, + - * / **, brackets, price fields and the listed functions are allowed.")

    walk(tree)
    return tree


def _rsi(x, n):
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def evaluate(expr: str, cols: dict):
    """The formula on `cols` (open..volume as Series for one stock, or as wide DataFrames for many)."""
    tree = check(expr)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            return cols[n.id]
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, ast.Pow):
                return ev(n.left) ** float(n.right.value)
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        f = n.func.id
        nser, window, _ = FUNCS[f]
        args = [ev(a) for a in n.args[:nser]]
        w = int(n.args[-1].value) if window else None
        x = args[0] if args else None
        if f == "sma":
            return x.rolling(w, min_periods=w).mean()
        if f == "ema":
            return x.ewm(span=w, adjust=False, min_periods=w).mean()
        if f == "rsi":
            return _rsi(x, w)
        if f == "highest":
            return x.rolling(w, min_periods=w).max()
        if f == "lowest":
            return x.rolling(w, min_periods=w).min()
        if f == "ref":
            return x.shift(w)
        if f == "stdev":
            return x.rolling(w, min_periods=w).std()
        if f == "sum":
            return x.rolling(w, min_periods=w).sum()
        if f == "roc":
            return (x / x.shift(w) - 1) * 100
        if f == "atr":
            h, lo, c = cols["high"], cols["low"], cols["close"]
            pc = c.shift(1)
            tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
            return tr.ewm(alpha=1 / w, adjust=False, min_periods=w).mean()
        if f == "abs":
            return abs(x)
        if f == "log":
            return np.log(x.where(x > 0)) if hasattr(x, "where") else (np.log(x) if x > 0 else np.nan)
        if f == "sqrt":
            return np.sqrt(x.where(x >= 0)) if hasattr(x, "where") else (np.sqrt(x) if x >= 0 else np.nan)
        if f == "max":
            return np.maximum(args[0], args[1])
        if f == "min":
            return np.minimum(args[0], args[1])
        raise FormulaError(f"Unknown function {f}")              # unreachable: check() refused it

    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = ev(tree)
    if isinstance(out, (int, float)):
        raise FormulaError("The formula must use at least one price field or function.")
    return out.replace([np.inf, -np.inf], np.nan)


# ---- saved formulas --------------------------------------------------------------------------------------------
def _path():
    return DATA_DIR / FILE


def saved() -> list[dict]:
    try:
        v = json.loads(_path().read_text(encoding="utf-8"))
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def save_all(items: list[dict]) -> list[dict]:
    out, names = [], set()
    for x in items[:MAX_SAVED]:
        name = re.sub(r"\s+", " ", str(x.get("name") or "")).strip()[:40]
        if not name:
            raise FormulaError("Every formula needs a name.")
        if name.lower() in names:
            raise FormulaError(f"Two formulas are called '{name}'.")
        names.add(name.lower())
        check(x.get("expr") or "")
        fid = str(x.get("id") or uuid.uuid4().hex[:8])
        if not re.fullmatch(r"[0-9a-f]{8}", fid):
            fid = uuid.uuid4().hex[:8]
        out.append({"id": fid, "name": name, "expr": str(x["expr"]).strip(),
                    "pane": "price" if x.get("pane") == "price" else "own"})
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1), encoding="utf-8")
    tmp.replace(_path())
    register_fields()
    return out


def register_fields() -> None:
    """Each saved formula as a scan field f_<id> (scanner/scans.py FIELDS), replacing the previous set."""
    from . import scans
    for k in [k for k in scans.FIELDS if k.startswith("f_")]:
        del scans.FIELDS[k]
    for x in saved():
        expr = x["expr"]
        scans.FIELDS[f"f_{x['id']}"] = scans.Field(
            f"{x['name']} (your formula)", "Your formulas", "",
            lambda c, e=expr: evaluate(e, {"open": c.p.open, "high": c.p.high, "low": c.p.low, "close": c.p.close,
                                           "volume": c.p.volume}))


def help_text() -> list[dict]:
    return [{"name": k, "help": v[2]} for k, v in FUNCS.items()]
