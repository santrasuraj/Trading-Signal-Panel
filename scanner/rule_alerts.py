"""Rule alerts (scanner/watch.py RULE_KINDS): conditions that need the daily history, not just a quote.

  rsi_above / rsi_below   RSI(14) of the daily closes with today's live price as the last close
  sma_above / sma_below   the live price above / below its N-day average (N = the alert's value)
  scan_hit                a saved scan (scanner/scans.py) gets a stock it did not have when the alert was set
  pattern                 a candle pattern whose 8-year study verdict is "edge" (pattern_study.py) completes on the
                          stock's daily chart (checked on completed days, after each scan)

Where they are checked: the 5-minute intraday job (intraday_sync.py --signals, quotes from the live service), the
dashboard's price stream (web/api/routers/stream.py) and the end of each scan (daily.py). Every alert still fires
once, under watch.py's file lock, whichever process sees it first.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import watch

LOOKBACK = 320                 # daily bars used (enough for a 200-day average and a settled RSI)
LIVE_KINDS = ("rsi_above", "rsi_below", "sma_above", "sma_below")


def with_live(close: pd.Series, price: float | None, day: date) -> pd.Series:
    """Daily closes with today's live price as the last close (replacing a provisional row for today)."""
    s = close.dropna().iloc[-LOOKBACK:]
    if price is None or not price > 0:
        return s
    ts = pd.Timestamp(day)
    if len(s) and s.index[-1] >= ts:
        s = s.copy()
        s.iloc[-1] = float(price)
        return s
    return pd.concat([s, pd.Series([float(price)], index=[ts])])


def rsi14(s: pd.Series) -> float | None:
    """Wilder's RSI(14) of the last value."""
    if len(s) < 15:
        return None
    d = s.diff().dropna()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    if dn == 0:
        return 100.0
    return float(100 - 100 / (1 + up / dn))


def live_check(a: dict, close: pd.DataFrame, quotes: dict, day: date) -> dict | None:
    k = a.get("kind")
    if k not in LIVE_KINDS:
        return None
    q = quotes.get(a.get("symbol"))
    if not q or (q.get("source") or "live") not in watch.LIVE_SOURCES or a.get("symbol") not in close.columns:
        return None
    price = q.get("price")
    s = with_live(close[a["symbol"]], price, day)
    v = float(a.get("value") or 0)
    if k.startswith("rsi"):
        r = rsi14(s)
        if r is None or not (r >= v if k == "rsi_above" else r <= v):
            return None
        return {"price": price, "source": q.get("source"), "detail": f"RSI {r:.1f}"}
    n = int(v)
    if len(s) < n or price is None:
        return None
    m = float(s.iloc[-n:].mean())
    if not (price > m if k == "sma_above" else price < m):
        return None
    return {"price": price, "source": q.get("source"), "detail": f"{n}-day average {m:,.2f}"}


def check_live(close: pd.DataFrame, quotes: dict, day: date | None = None) -> list[dict]:
    """Fire the RSI / moving-average alerts the live quotes ({symbol: quote}) meet."""
    day = day or watch.ist_now().date()
    return watch.fire(lambda a: live_check(a, close, quotes, day))


def check_patterns(frames: dict[str, pd.DataFrame], study: dict | None = None) -> list[dict]:
    """Fire 'pattern' alerts whose stock completed a candle pattern with a tested edge on its last daily bar."""
    from . import levels as lv
    from . import pattern_study
    want = {a["symbol"] for a in watch.alerts() if a.get("active") and a.get("kind") == "pattern"}
    if not want:
        return []
    study = study if study is not None else (pattern_study.load() or {})
    good = {k: p for k, p in (study.get("patterns") or {}).items() if p.get("verdict") == "edge"}
    found: dict[str, list[str]] = {}
    for s in want:
        if s not in frames["close"].columns:
            continue
        df = pd.DataFrame({f: frames[f][s] for f in ("open", "high", "low", "close")}).dropna().iloc[-40:]
        names = [good[p["key"]]["name"] for p in lv.patterns(df, last=1) if p.get("bars_ago", 0) == 0 and p["key"] in good]
        if names:
            found[s] = names
    if not found:
        return []
    last = frames["close"].dropna(how="all").index[-1]

    def chk(a):
        if a.get("kind") != "pattern" or a.get("symbol") not in found:
            return None
        return {"price": float(frames["close"].at[last, a["symbol"]]), "source": "close",
                "detail": ", ".join(found[a["symbol"]]) + f" ({last.date().isoformat()})"}
    return watch.fire(chk)


def scan_refs() -> list[str]:
    return sorted({a.get("ref") for a in watch.alerts() if a.get("active") and a.get("kind") == "scan_hit" and a.get("ref")})


def check_scans(hits: dict[str, list[str]], source: str = "scan") -> list[dict]:
    """Fire scan alerts whose scan (by id) now has stocks it did not have when the alert was set."""
    def chk(a):
        if a.get("kind") != "scan_hit" or a.get("ref") not in hits:
            return None
        new = [s for s in hits[a["ref"]] if s not in set(a.get("seen") or [])]
        return {"price": None, "source": source, "detail": "new: " + ", ".join(new[:12])} if new else None
    return watch.fire(chk)


def scan_hits(frames: dict[str, pd.DataFrame], symbols: list[str], quotes: dict | None = None,
              day: date | None = None) -> dict[str, list[str]]:
    """The stocks each saved scan with an active alert matches now: on the completed day, or with live quotes on
    today's row (only stocks with a live quote count then)."""
    from . import scans
    refs = scan_refs()
    if not refs:
        return {}
    saved = {s["id"]: s for s in scans.saved()}
    out = {}
    for ref in refs:
        sc = saved.get(ref)
        if not sc:
            continue
        r = (scans.run_live(sc, frames, quotes, symbols, day=day) if quotes is not None
             else scans.run_today(sc, frames, symbols))
        out[ref] = [row["symbol"] for row in r["rows"]]
    return out


def run_job(frames: dict[str, pd.DataFrame], symbols: list[str], quotes: dict, log=print) -> list[dict]:
    """The 5-minute job: RSI / average alerts and live scan hits on the live service's quotes; Telegram for any."""
    fired = check_live(frames["close"], quotes)
    try:
        fired += check_scans(scan_hits(frames, symbols, quotes), source="live")
    except Exception as e:                     # a broken saved scan must not stop the other alerts
        log(f"Scan alerts: {type(e).__name__}: {e}")
    if fired:
        watch.notify(fired)
        log("Alerts: " + "; ".join(watch.message(a) for a in fired))
    return fired


def end_of_day(frames: dict[str, pd.DataFrame], symbols: list[str], log=print) -> list[dict]:
    """After a scan: candle-pattern alerts and scan alerts on the completed day; Telegram for any."""
    fired = []
    for step in (lambda: check_patterns(frames), lambda: check_scans(scan_hits(frames, symbols))):
        try:
            fired += step()
        except Exception as e:
            log(f"Rule alerts: {type(e).__name__}: {e}")
    if fired:
        watch.notify(fired)
        log("Alerts: " + "; ".join(watch.message(a) for a in fired))
    return fired


__all__ = ["with_live", "rsi14", "check_live", "check_patterns", "check_scans", "scan_hits", "run_job", "end_of_day"]
