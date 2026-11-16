"""Dividends and rights issues from NSE's corporate-actions list (www.nseindia.com/api/corporates-corporateActions).

One request per quarter (cached in data/nse/ca_YYYYqN.json; past quarters never change, the current one is refreshed
daily). NSE lists each action under today's symbol, with its ex-date, face value and purpose text:
  "Interim Dividend - Rs 5 Per Share", "Final Dividend - Re 0.60 Per Share And Special Dividend - Rs 3 Per Share",
  "Dividend - 25%" (of face value, older notices), "Rights 1:5 @ Premium Rs 95/-".

Used for:
  - total-return backtests: a stock held before its ex-date pays its dividend in cash (engine.simulate), as a yield
    on the previous close (`yields`): Rs D per share / the raw close before the ex-date, so it holds whatever later
    splits did to the price units;
  - rights issues: on the ex-date NSE re-bases the previous close to the theoretical ex-rights price, so the history
    before it is rescaled by NSE's base / the raw close (pit.py and store.py), and the ex-rights day no longer shows a
    fake loss.
Nothing here guesses: a purpose whose amount can't be read is counted (`parse` report) and left out.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

import numpy as np
import pandas as pd

from . import nse

EQUITY_SERIES = {"EQ", "BE", "BZ"}
REFRESH_S = 20 * 3600          # the current quarter's list is asked again after this
MAX_YIELD = 0.25               # a "dividend" above 25% of the price is a capital distribution: pit.py handles those
DIV_WORD = re.compile(r"DIV", re.I)
RUPEES = re.compile(r"(?:RS|RE|INR)\.?\s*-?\s*(\d+(?:\.\d+)?)", re.I)
PER_SHARE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:/-)?\s*PER\s*SH", re.I)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
RIGHTS = re.compile(r"\bRIGHTS?\b", re.I)
RIGHTS_RATIO = re.compile(r"RIGHTS?\W{0,4}(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
RIGHTS_PREMIUM = re.compile(r"PREMIUM\W*(?:OF\W*)?(?:RS|RE|INR)?\.?\W*(\d+(?:\.\d+)?)", re.I)
RIGHTS_PRICE = re.compile(r"@\s*(?:RS|RE|INR)\.?\s*(\d+(?:\.\d+)?)", re.I)
NOT_SHARES = re.compile(r"DEBENTURE|NCD|CCD|WARRANT|PREF|BOND|PARTLY", re.I)


def _quarters(start: date, end: date) -> list[tuple[int, int]]:
    out, y, q = [], start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


NETWORK = True                 # tests switch this off (conftest.py): only cached quarters are read then


def _dir():
    return nse.NSE_DIR


def _cache_file(y: int, q: int):
    return _dir() / f"ca_{y}q{q}.json"


def fetch_quarter(y: int, q: int, today: date | None = None, get_json=None, offline: bool = False) -> list[dict] | None:
    """All corporate actions with an ex-date in quarter q of year y (cached). None if NSE can't be reached.
    `offline`: the cached list only, however old (the point-in-time update runs without the network)."""
    today = today or date.today()
    p = _cache_file(y, q)
    current = (y, q) >= (today.year, (today.month - 1) // 3 + 1)
    if p.exists() and (offline or not NETWORK or not current or time.time() - p.stat().st_mtime < REFRESH_S):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if offline or not NETWORK:
        return None
    if get_json is None:
        from .events import _get_json as get_json
    m0 = 3 * (q - 1) + 1
    start = date(y, m0, 1)
    end = (date(y + 1, 1, 1) if q == 4 else date(y, m0 + 3, 1)) - pd.Timedelta(days=1)
    try:
        rows = get_json("corporates-corporateActions", {"index": "equities", "from_date": start.strftime("%d-%m-%Y"),
                                                        "to_date": end.strftime("%d-%m-%Y")})
    except Exception:
        rows = None
    if not isinstance(rows, list):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    _dir().mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    return rows


def dividend_amount(subject: str, face_value: float | None) -> float | None:
    """Rupees per share in a dividend purpose (several dividends in one text are added up); None if unreadable."""
    total, found = 0.0, False
    for part in re.split(r"\s+(?:AND|&)\s+|/|;|,(?=\s*[A-Z])", subject, flags=re.I):
        if not DIV_WORD.search(part):
            continue
        m = RUPEES.search(part)
        if m:
            total += float(m.group(1))
            found = True
            continue
        m = PER_SHARE.search(part)
        if m:
            total += float(m.group(1))
            found = True
            continue
        m = PERCENT.search(part)
        if m and face_value:
            total += float(m.group(1)) / 100 * face_value
            found = True
    return round(total, 4) if found and total > 0 else None


def _date(s) -> pd.Timestamp | None:
    try:
        ts = pd.to_datetime(str(s).strip(), format="%d-%b-%Y")
    except (ValueError, TypeError):
        return None
    return None if pd.isna(ts) else ts


def parse(rows: list[dict]) -> tuple[pd.DataFrame, dict]:
    """(actions, report): one row per (symbol, ex-date, kind) with kind 'dividend' (amount in Rs per share) or
    'rights'; the report counts dividends whose amount couldn't be read."""
    out, unread = [], 0
    for r in rows or []:
        if str(r.get("series") or "").strip() not in EQUITY_SERIES:
            continue
        subj = re.sub(r"\s+", " ", str(r.get("subject") or "")).strip()
        ex = _date(r.get("exDate"))
        sym = str(r.get("symbol") or "").strip().upper()
        if ex is None or not sym:
            continue
        try:
            fv = float(str(r.get("faceVal") or "").strip())
        except ValueError:
            fv = None
        if DIV_WORD.search(subj) and not re.search(r"DIVISION", subj, re.I):
            amt = dividend_amount(subj, fv)
            if amt is None:
                unread += 1
            else:
                out.append({"symbol": sym, "ex_date": ex, "kind": "dividend", "amount": amt, "subject": subj})
        if RIGHTS.search(subj):
            terms = rights_terms(subj, fv) or (np.nan, np.nan, np.nan)
            out.append({"symbol": sym, "ex_date": ex, "kind": "rights", "amount": np.nan, "subject": subj,
                        "new": terms[0], "held": terms[1], "price": terms[2]})
    df = pd.DataFrame(out, columns=["symbol", "ex_date", "kind", "amount", "subject", "new", "held", "price"])
    if len(df):
        # NSE repeats an action across series and in corrected notices ("Date Revised"): the same amount on the same
        # ex-date counts once; different amounts that day (an interim and a special dividend listed apart) add up
        df = df.drop_duplicates(["symbol", "ex_date", "kind", "amount"])
        df = df[(df["kind"] != "rights") | ~df.duplicated(["symbol", "ex_date", "kind"])]
        df = (df.groupby(["symbol", "ex_date", "kind"], as_index=False)
                .agg(amount=("amount", "sum"), subject=("subject", " + ".join), new=("new", "first"),
                     held=("held", "first"), price=("price", "first")))
    return df.sort_values(["ex_date", "symbol"]).reset_index(drop=True), {"rows": len(rows or []), "dividend_unread": unread}


def actions(start: date, end: date | None = None, log=print, get_json=None, offline: bool = False) -> pd.DataFrame:
    """Dividends and rights issues with ex-dates between start and end (NSE, cached per quarter)."""
    end = end or date.today()
    rows, missing = [], []
    for y, q in _quarters(start, end):
        got = fetch_quarter(y, q, get_json=get_json, offline=offline)
        if got is None:
            missing.append(f"{y} Q{q}")
        else:
            rows.extend(got)
    if missing and not offline and NETWORK:
        log(f"Dividends: NSE's corporate-actions list unavailable for {', '.join(missing)} - those quarters count no dividends")
    df, rep = parse(rows)
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return df[(df["ex_date"] >= s) & (df["ex_date"] <= e)].reset_index(drop=True)


def yields(close: pd.DataFrame, raw_close: pd.DataFrame | None, acts: pd.DataFrame,
           symbol_then=None) -> pd.DataFrame:
    """Dividend yield on each ex-date (rows = dates, columns = symbols, 0 elsewhere): Rs per share / the raw close of
    the trading day before. `raw_close`: NSE's unadjusted closes (the point-in-time panel), else `close` is used,
    which is right only where no split happened later (it is the adjusted price). `symbol_then(sym, day)` maps
    today's symbol to the one traded then, for raw panels kept under the old symbol (unused when raw is wide by
    today's symbol)."""
    out = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    divs = acts[acts["kind"] == "dividend"]
    if divs.empty:
        return out
    ref = (raw_close if raw_close is not None else close).reindex(index=close.index).ffill()
    idx, cols = close.index, {c: j for j, c in enumerate(ref.columns)}
    vals, res = ref.to_numpy(dtype=float), out.to_numpy(dtype=float, copy=True)
    ocols = {c: j for j, c in enumerate(out.columns)}
    for r in divs.itertuples(index=False):
        j, k = cols.get(r.symbol), ocols.get(r.symbol)
        if j is None or k is None:
            continue
        i = idx.searchsorted(r.ex_date)
        if i >= len(idx) or i == 0 or idx[i] != r.ex_date:
            continue                      # ex-date not a trading day in the panel (or before its start)
        prev = vals[i - 1, j]             # the last close before the ex-date (carried over non-trading days)
        if not prev > 0:
            continue
        y = float(r.amount) / prev
        if 0 < y <= MAX_YIELD:
            res[i, k] += y
    return pd.DataFrame(res, index=out.index, columns=out.columns)


def total_return(price: pd.Series | None, dy_pct: pd.Series | None) -> pd.Series | None:
    """A price index as a total-return index: each day's move plus the dividends accrued at NSE's published
    dividend yield of the day before (dy_pct, % a year) over the calendar days between. NSE's own TRI reinvests on
    each ex-date instead; over months the two agree closely. Days without a yield accrue nothing."""
    if price is None or dy_pct is None:
        return price
    p = price.dropna()
    if p.empty:
        return price
    dy = dy_pct.reindex(p.index).ffill().fillna(0.0).clip(lower=0.0, upper=20.0)
    days = p.index.to_series().diff().dt.days.fillna(0).to_numpy(dtype=float)
    accr = 1 + dy.shift(1).fillna(0.0).to_numpy() / 100 * days / 365.0
    tr = (p / p.shift(1)).fillna(1.0).to_numpy() * accr
    out = pd.Series(tr.cumprod() * float(p.iloc[0]), index=p.index, name=price.name)
    return out.reindex(price.index)


def rights_terms(subject: str, face_value: float | None) -> tuple[float, float, float] | None:
    """(new shares, held shares, issue price) of an equity rights issue: "Rights 3:2 @ Premium Rs 62.50" is 3 new
    shares for every 2 held at face value + 62.50. None for debentures / warrants / partly paid shares, or when the
    price can't be read (the first class is used when several are offered)."""
    subject = re.split(r"\s/\s", subject)[0]          # several classes offered: the first one
    if NOT_SHARES.search(subject):
        return None
    m = RIGHTS_RATIO.search(subject)
    if not m:
        return None
    new, held = float(m.group(1)), float(m.group(2))
    rest = subject[m.end():]
    p = RIGHTS_PREMIUM.search(rest)
    if p:
        price = (face_value + float(p.group(1))) if face_value else None
    elif re.search(r"@\s*PAR\b", rest, re.I):
        price = face_value
    else:
        q = RIGHTS_PRICE.search(rest)
        price = float(q.group(1)) if q else None
    if not (new > 0 and held > 0 and price and price > 0):
        return None
    return new, held, price


def rights_factors(close: pd.DataFrame, acts: pd.DataFrame, skip: set | None = None,
                   tolerance: float = 0.005) -> list[dict]:
    """History adjustments for equity rights issues. NSE does not re-base the previous close for them, so the
    theoretical ex-rights price comes from the terms: TERP = (held x P + new x issue price) / (held + new), with P
    the raw close before the ex-date (`close`: NSE's raw panel), and the history before the ex-date is rescaled by
    TERP / P. `skip`: (date, symbol) pairs already adjusted for something else (a big ex-rights drop the build
    matched to the reference history, a split the same day). An issue priced at or above the market changes
    nothing (nobody would take it up)."""
    out = []
    idx = close.index
    ref = close.ffill()
    for r in acts[acts["kind"] == "rights"].itertuples(index=False):
        s, d = r.symbol, r.ex_date
        if s not in close.columns or (skip and (d, s) in skip) or not (r.new > 0 and r.held > 0 and r.price > 0):
            continue
        i = idx.searchsorted(d)
        if i >= len(idx) or i == 0 or idx[i] != d:
            continue
        p = ref.iat[i - 1, ref.columns.get_loc(s)]
        if not p > 0:
            continue
        f = (r.held + r.new * r.price / p) / (r.held + r.new)
        if 0.2 < f < 1 - tolerance:
            out.append({"symbol": s, "date": d.date().isoformat(), "factor": round(float(f), 6),
                        "reason": f"RIGHTS: {r.subject} (theoretical ex-rights price)"})
    return out
