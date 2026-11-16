"""Seasonality across the market (GET /api/seasonal?period=11 | budget | ...): scanner/seasonal.py on the price store
(today's universe: the stock lists, the sector grid, NIFTY 500's record) and on the point-in-time top 500 (the
walk-forward test, so stocks that later collapsed or were delisted count). Cached per store generation and
point-in-time build; a period's chance test and walk-forward are cached once computed."""
from __future__ import annotations

import threading

import pandas as pd

from scanner import seasonal as sz
from scanner.costs import CostModel
from scanner.providers import INDEX_N500

from . import data
from ..errors import ApiException
from ..util import today_ist

BENCH = INDEX_N500
_lock = threading.Lock()
_base: dict = {}
_periods: dict = {}

NOTE = ("Calendar-month returns from month-end closes (a season compounds its months), measured against the NIFTY 500 "
        "so a strong market month does not make every stock look seasonal. About eight years per month is a small "
        "sample and ~500 stocks give many chances for luck: compare each list with the count noise alone produces, "
        "and with the walk-forward test, before trusting it. Descriptive base rates, not a forecast.")


def _key() -> tuple:
    close = data.store_close()
    try:
        from scanner.pit import PIT_DIR
        pit = (PIT_DIR / "CURRENT").read_text(encoding="utf-8").strip()
    except OSError:
        pit = None
    return (str(close.index[-1]) if len(close) else None, close.shape, pit)


def _universe(close: pd.DataFrame) -> list[str]:
    uni = data.universe()
    syms = [s for s in uni["symbol"].astype(str)] if len(uni) else []
    syms = [s for s in syms if s in close.columns and s != BENCH]
    if not syms:                                     # no universe file: every stock column of the store
        from scanner.providers import INDEX_SYMBOLS
        syms = [s for s in close.columns if s not in INDEX_SYMBOLS]
    return syms


def _cost_pct(cfg: dict) -> float:
    cap = float(((cfg.get("account") or {}).get("capital")) or 500000)
    return CostModel.from_config(cfg.get("costs")).round_trip_pct(max(cap / sz.TOP_N, 10000.0))


def _pit_panel(store_close: pd.DataFrame):
    """(monthly returns of every point-in-time stock plus the bench, month-start membership, 'point_in_time') - or the
    store's own list (flattered: survivors only) when the point-in-time cache is not built."""
    try:
        from scanner import pit
        p = pit.load()
    except Exception:
        p = None
    if p is not None and BENCH in store_close.columns:
        close = p.frames["close"].copy()
        close[BENCH] = store_close[BENCH].reindex(close.index)
        uni = p.universe
        member = uni.groupby(uni.index.to_period("M")).first()
        return sz.monthly_returns(close), member, "point_in_time"
    syms = _universe(store_close)
    mret = sz.monthly_returns(store_close[syms + [BENCH]])
    member = pd.DataFrame(True, index=mret.index, columns=syms)
    return mret, member, "current"


def _build() -> dict:
    close = data.store_close()
    if BENCH not in close.columns or len(close) < 300:
        raise ApiException("FEATURE_UNAVAILABLE", "Not enough price history for seasonality yet.",
                           "Run a scan first.", {"feature": "seasonal"})
    syms = _universe(close)
    mret = sz.monthly_returns(close[syms + [BENCH]])
    meta = data.symbol_meta()
    industry = {s: (meta.get(s) or {}).get("industry") for s in syms}
    pit_mret, member, universe = _pit_panel(close)
    cfg = data.config()
    return {"close": close, "syms": syms, "mret": mret, "meta": meta, "industry": industry,
            "sectors": sz.sector_grid(mret, BENCH, industry), "pit_mret": pit_mret, "member": member,
            "universe": universe, "cost_pct": _cost_pct(cfg), "pooled": {}}


def _base_data() -> dict:
    k = _key()
    with _lock:
        if _base.get("key") != k:
            _base.clear()
            _periods.clear()
            _base.update(key=k, **_build())
        return _base


def _walk(b: dict, p: dict) -> list[dict]:
    res = sz.walk_forward(b["pit_mret"], b["member"], BENCH, p["months"], b["cost_pct"])
    for r in res:
        r["label"] = f"{p['short']} {r['year']}"
        r["month"] = p["months"][0]
    return res


def _pooled(b: dict, kind: str) -> dict:
    """The walk-forward pooled over every month (or every season): the test's real sample size."""
    if kind not in b["pooled"]:
        rows = []
        for p in sz.period_list():
            if p["kind"] == kind:
                rows += _walk(b, p)
        rows.sort(key=lambda r: (r["year"], r["month"]))
        b["pooled"][kind] = sz.summarize(rows)
    return b["pooled"][kind]


def _so_far(close: pd.DataFrame, months: tuple[int, ...], syms: list[str]) -> tuple[pd.Series, float] | None:
    """Return so far this year in a period that is under way (from the close before it started to the last close)."""
    today = today_ist()
    if today.month not in months:
        return None
    start = pd.Timestamp(year=today.year, month=min(months), day=1)
    before = close.loc[close.index < start]
    if before.empty or close.index[-1] < start:
        return None
    base, last = before.iloc[-1], close.iloc[-1]
    pct = (last[syms] / base[syms] - 1) * 100
    return pct, float((last[BENCH] / base[BENCH] - 1) * 100)


def view(period: str | None = None) -> dict:
    today = today_ist()
    key = str(period) if period else str(today.month)
    p = sz.find_period(key)
    if p is None:
        raise ApiException("VALIDATION", "period must be a month number (1-12) or a season: "
                           + ", ".join(s["key"] for s in sz.SEASONS) + ".")
    b = _base_data()
    with _lock:
        cached = _periods.get(p["key"])
    if cached is None:
        cached = _period(b, p)
        with _lock:
            _periods[p["key"]] = cached
    return {**cached, "periods": [{k: x[k] for k in ("key", "kind", "name", "short", "months")} for x in sz.period_list()],
            "current": {"month": str(today.month), "season": sz.season_of(today.month)["key"]},
            "sectors": b["sectors"], "as_of": str(b["close"].index[-1].date()), "note": NOTE}


def _period(b: dict, p: dict) -> dict:
    close, syms, mret = b["close"], b["syms"], b["mret"]
    per = sz.period_returns(mret, p["months"])
    st = sz.stock_stats(per[syms], per[BENCH])
    st = st[st["n"] >= sz.MIN_YEARS] if not st.empty else st
    so = _so_far(close, p["months"], syms)
    rows = []
    for r in st.to_dict("records"):
        m = b["meta"].get(r["symbol"]) or {}
        row = {"symbol": r["symbol"], "company": m.get("company"), "industry": m.get("industry"),
               "side": "bullish" if r["excess_pct"] > 0 else "bearish", "n": r["n"], "avg_pct": sz._r(r["avg_pct"]),
               "median_pct": sz._r(r["median_pct"]), "excess_pct": sz._r(r["excess_pct"]),
               "median_excess_pct": sz._r(r["median_excess_pct"]), "beat_pct": sz._r(r["beat_pct"], 0),
               "up_pct": sz._r(r["up_pct"], 0), "t": sz._r(r["t"]), "strength": r["strength"],
               "years": {str(y): sz._r(v) for y, v in r["years"].items()}, "so_far_pct": None, "so_far_excess_pct": None}
        if so is not None:
            v = so[0].get(r["symbol"])
            if v is not None and pd.notna(v):
                row["so_far_pct"], row["so_far_excess_pct"] = sz._r(float(v)), sz._r(float(v) - so[1])
        rows.append(row)
    cnt = {side: {s: sum(1 for r in rows if r["side"] == side and r["strength"] == s) for s in ("consistent", "lean")}
           for side in ("bullish", "bearish")}
    chance = sz.chance_counts(mret[syms + [BENCH]], BENCH, p["months"])
    test_rows = _walk(b, p)
    years = sorted({int(y) for y in per.index if per[BENCH].notna().get(y, False)})
    return {"period": {k: p[k] for k in ("key", "kind", "name", "short", "months", "why")}, "bench": "NIFTY 500",
            "first_year": years[0] if years else None, "last_year": years[-1] if years else None,
            "market": sz.bench_stats(per[BENCH]), "rows": rows,
            "in_progress": so is not None, "market_so_far_pct": sz._r(so[1]) if so is not None else None,
            "counts": {**cnt, "chance": chance, "min_years": sz.MIN_YEARS},
            "test": {"rows": test_rows, "summary": sz.summarize(test_rows), "pooled": _pooled(b, p["kind"]),
                     "universe": b["universe"], "cost_pct": sz._r(b["cost_pct"]), "top_n": sz.TOP_N,
                     "train_min_years": sz.TRAIN_MIN_YEARS}}
