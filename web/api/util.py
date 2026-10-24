"""Small helpers shared by the services."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from scanner.settings import IST


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def num(x: Any, nd: int | None = None) -> float | None:
    """float or None (NaN, inf, None, non-numeric -> None); optionally rounded."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


def inum(x: Any) -> int | None:
    v = num(x)
    return int(round(v)) if v is not None else None


def sub(a: Any, b: Any, nd: int | None = 2) -> float | None:
    a, b = num(a), num(b)
    return None if a is None or b is None else (round(a - b, nd) if nd is not None else a - b)


def ser_list(s, nd: int | None = None) -> list:
    """numpy / pandas values -> JSON list with NaN -> None (vectorised, fast for long series)."""
    arr = np.asarray(s, dtype=float)
    if nd is not None:
        arr = np.round(arr, nd)
    ok = np.isfinite(arr)
    out = arr.tolist()
    if not ok.all():
        for i in np.flatnonzero(~ok):
            out[i] = None
    return out


def iso_date(x: Any) -> str | None:
    """'YYYY-MM-DD' or None (None / NaN / NaT / unparseable -> None; NaT.isoformat() would be 'NaT')."""
    try:
        if x is None or pd.isna(x):
            return None
        return pd.Timestamp(x).date().isoformat()
    except (TypeError, ValueError):
        return None


def fmt_date(d: Any, year: bool = True) -> str:
    """A date for server-written TEXT in the UI's format: '30 Oct' or '22 Oct 2026' (no leading zero)."""
    try:
        ts = pd.Timestamp(str(d)[:10])
    except (TypeError, ValueError):
        return str(d)
    if pd.isna(ts):
        return str(d)
    out = f"{ts.day} {ts.strftime('%b')}"
    return f"{out} {ts.year}" if year else out


def inr(x: Any, nd: int = 0) -> str:
    """Rupees with Indian digit grouping for server-written text: 500000 -> '₹5,00,000'."""
    v = num(x)
    if v is None:
        return "—"
    whole, _, frac = f"{abs(v):.{nd}f}".partition(".")
    if len(whole) > 3:
        head, groups = whole[:-3], [whole[-3:]]
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups)
    return f"{'−' if v < 0 else ''}₹{whole}{'.' + frac if frac else ''}"


def spct(x: Any, nd: int = 1) -> str:
    """Signed percent for server-written text with a real minus sign: '+1.2%', '−20.7%'."""
    v = num(x)
    if v is None:
        return "—"
    s = f"{abs(v):.{nd}f}"
    if float(s) == 0:
        return f"{s}%"
    return f"{'+' if v > 0 else '−'}{s}%"


def iso_dt_from_epoch(x: Any) -> str | None:
    v = num(x)
    if v is None:
        return None
    return datetime.fromtimestamp(v, IST).isoformat(timespec="seconds")


def days_until(d: str | None, today: date | None = None) -> int | None:
    if not d:
        return None
    try:
        return (date.fromisoformat(str(d)[:10]) - (today or today_ist())).days
    except ValueError:
        return None


def sample_even(values: list, n: int) -> list:
    """<= n evenly spaced points, always including the last one."""
    if len(values) <= n:
        return list(values)
    idx = np.linspace(0, len(values) - 1, n).round().astype(int)
    return [values[i] for i in idx]
