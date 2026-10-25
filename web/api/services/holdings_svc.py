"""Your holdings: health as of the last scan (latest.holdings) + the current holdings.csv.

holdings.csv is per CHECKOUT (ROOT/holdings.csv): scans started from another checkout read their own copy,
so holdings health is only correct for scans started by this platform until the branch merges.
"""
from __future__ import annotations

import math
import re
from datetime import date

import pandas as pd

from scanner.holdings import HOLDING_COLS, save_holdings

from . import data, strategies as st
from ..paths import P
from ..util import inum, iso_date, num, today_ist

_RENAMED = re.compile(r"^(\S+) is now traded as (\S+)$")     # daily.py's rename alert (current_symbol note)


def _inputs() -> list[dict]:
    out = []
    for r in data.holdings_df().itertuples(index=False):
        # an empty buy date parses to NaT, which is a date subclass whose isoformat() is "NaT"
        out.append({"symbol": r.symbol, "qty": num(r.qty), "buy_price": num(r.buy_price),
                    "buy_date": iso_date(r.buy_date),
                    "stop_loss_pct": num(r.stop_loss_pct), "target_pct": num(r.target_pct)})
    return out


def _renamed(scanned: dict[str, dict]) -> dict[str, str]:
    """old symbol -> the symbol the last scan priced it under (holdings.csv still says e.g. TATAMOTORS; the
    scan follows the NSE rename to TMPV and says so in an alert). Read from the alerts: no NSE download here."""
    out = {}
    for sym, h in scanned.items():
        for a in h.get("alerts") or []:
            m = _RENAMED.match(str(a))
            if m and m.group(2) == sym:
                out[m.group(1)] = sym
    return out


def _in_models(lt: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in lt.get("strategies") or []:
        for p in s.get("positions") or []:
            out.setdefault(p.get("symbol"), []).append(s.get("key"))
    return out


def _generated_epoch(lt: dict) -> float | None:
    try:
        return pd.Timestamp(lt["generated_at"]).timestamp()
    except Exception:
        return None


_PRICE_ALERT = ("STOP-LOSS HIT", "TARGET REACHED")                       # daily.py's buy-price alerts
_TREND_ALERT = ("Closed below its 50-day average", "Below its 200-day average", "No fresh price today")
_CORP_ALERT = "Corporate action since your buy date"
CHANGED_NOTE = "Quantity, buy price, stop or target changed after the last scan - re-check to refresh every alert."
ADDED_NOTE = "Added after the last scan: stop, target and trend from the latest prices - re-check for the full check."


def _defaults() -> tuple[float, float]:
    hd = data.config().get("holdings_defaults") or {}
    return num(hd.get("stop_loss_pct")) or 8.0, num(hd.get("target_pct")) or 20.0


def _pcts(i: dict, dsl: float, dtg: float) -> tuple[float, float]:
    return (i["stop_loss_pct"] if i["stop_loss_pct"] is not None else dsl,
            i["target_pct"] if i["target_pct"] is not None else dtg)


def _close(a, b, rel: float, abs_tol: float = 0.0) -> bool:
    a, b = num(a), num(b)
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), abs_tol)


def _flag(v) -> bool | None:
    if v is None:
        return None
    try:
        return None if pd.isna(v) else bool(v)
    except (TypeError, ValueError):
        return None


def _same(i: dict, h: dict, sl: float, tg: float) -> bool:
    """Did the last scan check this holdings.csv row as it is now? The scan restates qty and buy price after a
    split/bonus (qty / f, buy x f), which keeps qty x buy; otherwise both are compared directly (qty is rounded
    to whole shares in latest.json). Stop / target % are compared through the scan's stop and target prices."""
    if num(h.get("price")) is None:          # the scan found no price for it: nothing to compare
        return True
    sq, sb = num(h.get("qty")), num(h.get("buy_price"))
    if any(str(a).startswith(_CORP_ALERT) for a in h.get("alerts") or []):
        if not _close((i["qty"] or 0) * (i["buy_price"] or 0), (sq or 0) * (sb or 0), 0.02):
            return False
    elif not (_close(i["buy_price"], sb, 1e-5, 0.0051) and abs((i["qty"] or 0) - (sq or 0)) < 0.5):
        return False         # (latest.json rounds the buy price to 2 dp and the quantity to whole shares)
    if sb:
        if h.get("stop_price") is not None and not _close(h["stop_price"], sb * (1 - sl / 100), 1e-3, 0.011):
            return False
        if h.get("target_price") is not None and not _close(h["target_price"], sb * (1 + tg / 100), 1e-3, 0.011):
            return False
    return True


def _health(px: float | None, qty: float | None, buy: float | None, sl: float, tg: float,
            other_alerts: list[str]) -> dict:
    """daily.py's holding check for one row whose price and trend alerts are already known."""
    alerts: list[str] = []
    stop_hit = target_hit = False
    if px is not None and buy:
        if px <= buy * (1 - sl / 100):
            alerts.append(f"STOP-LOSS HIT: down more than {sl:g}% from your buy price")
            stop_hit = True
        elif px >= buy * (1 + tg / 100):
            alerts.append(f"TARGET REACHED: up more than {tg:g}% - consider booking part / trailing your stop")
            target_hit = True
    trend = any(str(a).startswith(_TREND_ALERT) for a in other_alerts)
    level = ("unknown" if px is None else "danger" if stop_hit else "watch" if trend else "good" if target_hit
             else "ok")
    return {"qty": qty, "buy_price": buy, "price": px,
            "pnl_pct": round((px / buy - 1) * 100, 2) if px is not None and buy else None,
            "pnl_amount": round((px - buy) * qty, 2) if px is not None and buy and qty is not None else None,
            "stop_price": round(buy * (1 - sl / 100), 2) if buy else None,
            "target_price": round(buy * (1 + tg / 100), 2) if buy else None,
            "level": level, "alerts": alerts + other_alerts}


def _restated(i: dict, h: dict, sl: float, tg: float) -> dict:
    """A scanned row whose holdings.csv inputs changed after the scan: the scan's price and trend, today's inputs."""
    corp = any(str(a).startswith(_CORP_ALERT) for a in h.get("alerts") or [])
    same_size = corp and _close((i["qty"] or 0) * (i["buy_price"] or 0),
                                (num(h.get("qty")) or 0) * (num(h.get("buy_price")) or 0), 0.02)
    # only stop/target changed after a split: keep the scan's split-adjusted qty and buy price
    qty, buy = (num(h.get("qty")), num(h.get("buy_price"))) if same_size else (i["qty"], i["buy_price"])
    keep = [str(a) for a in h.get("alerts") or [] if not str(a).startswith(_PRICE_ALERT)
            and (same_size or not str(a).startswith(_CORP_ALERT))]
    return {**h, **_health(num(h.get("price")), qty, buy, sl, tg, keep + [CHANGED_NOTE])}


def _fresh(i: dict, sym: str, sl: float, tg: float, results_on: str | None) -> dict:
    """A holding added after the last scan: price, rank, RS and trend from the scan's screener (else the store)."""
    sc = data.screener()
    hit = sc[sc["symbol"] == sym] if sc is not None else None
    row = hit.iloc[0].to_dict() if hit is not None and len(hit) else {}
    if row:
        px, chg = num(row.get("price"), 2), num(row.get("change_pct"), 2)
    else:
        px, chg = _last_quote(sym)
    trend = []
    if _flag(row.get("fresh")) is False:
        trend.append("No fresh price today - possibly suspended/renamed")
    if _flag(row.get("above_sma50")) is False:
        trend.append("Closed below its 50-day average (trend weakening)")
    if _flag(row.get("above_sma200")) is False:
        trend.append("Below its 200-day average (long-term downtrend)")
    if results_on:
        trend.insert(0, f"Quarterly results on {pd.Timestamp(results_on):%d %b} - expect a big move either way")
    if px is None:
        notes = ["No price data yet - check the NSE symbol, then re-check."]
    else:
        notes = [ADDED_NOTE]
    out = {"symbol": sym, "change_pct": chg, "momentum_rank": row.get("momentum_rank"), "rs": row.get("rs"),
           "results_on": results_on, **_health(px, i["qty"], i["buy_price"], sl, tg, trend + notes)}
    return out


def rows(lt: dict | None) -> tuple[list[dict], bool]:
    """One row per holdings.csv row as it is NOW (a holding removed after the scan is gone), with the health the
    last scan computed; rows added or edited after the scan are re-checked here on the scan's prices."""
    lt = lt or {}
    meta = data.symbol_meta()
    models = _in_models(lt)
    inputs = _inputs()
    # daily.py writes one health row per holdings.csv row, in file order: lot k of a symbol is compared with
    # lot k of the scan (comparing every lot with the last one would flag the earlier lots as changed forever)
    lots: dict[str, list[dict]] = {}
    for h in lt.get("holdings") or []:
        lots.setdefault(h.get("symbol"), []).append(h)
    scanned = {k: v[0] for k, v in lots.items()}
    renamed = _renamed(scanned)
    dsl, dtg = _defaults()
    soon: dict[str, str] | None = None
    out, changed = [], False
    for i in inputs:
        sym = renamed.get(i["symbol"], i["symbol"])     # holdings.csv may still say e.g. TATAMOTORS
        sl, tg = _pcts(i, dsl, dtg)
        q = lots.get(sym)
        h = q.pop(0) if q else None
        if h is None:
            if soon is None:
                from . import results as results_svc
                soon = {e["symbol"]: e["date"] for e in results_svc.events(lt, days=14)["events"]}
            out.append(_row(_fresh(i, sym, sl, tg, soon.get(sym)), meta, models))
            changed = True
        elif _same(i, h, sl, tg):
            out.append(_row(h, meta, models))
        else:
            out.append(_row(_restated(i, h, sl, tg), meta, models))
            changed = True
    total = sum(r["value"] for r in out if r["value"] is not None)
    for r in out:
        r["weight_pct"] = round(r["value"] / total * 100, 2) if total and r["value"] is not None else None
    stale = changed
    gen = _generated_epoch(lt)
    try:
        if gen is not None and P.holdings.exists() and P.holdings.stat().st_mtime > gen:
            stale = True
    except OSError:
        pass
    if {renamed.get(i["symbol"], i["symbol"]) for i in inputs} != set(scanned):
        stale = True
    return out, stale


def _last_quote(sym: str) -> tuple[float | None, float | None]:
    """(last close, 1-day change %) from the scan's screener row, else from the price store."""
    sc = data.screener()
    if sc is not None:
        hit = sc[sc["symbol"] == sym]
        if len(hit):
            chg = hit["change_pct"].iloc[0] if "change_pct" in hit.columns else None
            return num(hit["price"].iloc[0]), num(chg, 2)
    try:
        c = data.store_close()
    except Exception:
        return None, None
    if sym in c.columns:
        s = c[sym].dropna()
        if len(s):
            return num(s.iloc[-1], 2), (num((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2) if len(s) > 1 else None)
    return None, None


def _row(h: dict, meta: dict, models: dict) -> dict:
    sym = h.get("symbol")
    m = meta.get(sym, {})
    qty, price, chg = num(h.get("qty")), num(h.get("price")), num(h.get("change_pct"))
    value = round(qty * price, 2) if qty is not None and price is not None else None
    day = round(value * chg / (100 + chg), 2) if value is not None and chg is not None and chg > -100 else None
    level = h.get("level") if h.get("level") in ("ok", "good", "watch", "danger", "unknown") else "unknown"
    return {"symbol": sym, "company": h.get("company") or m.get("company"), "industry": m.get("industry"),
            "qty": qty, "buy_price": num(h.get("buy_price")), "price": price, "change_pct": chg,
            "pnl_pct": num(h.get("pnl_pct")), "pnl_amount": num(h.get("pnl_amount")),
            "stop_price": num(h.get("stop_price")), "target_price": num(h.get("target_price")),
            "momentum_rank": inum(h.get("momentum_rank")), "rs": num(h.get("rs")), "results_on": h.get("results_on"),
            "level": level, "alerts": [str(a) for a in h.get("alerts") or []], "value": value, "day_pnl": day,
            "weight_pct": None, "in_models": models.get(sym, [])}


def response(lt: dict | None) -> dict:
    rs, stale = rows(lt)
    inv = [(r["qty"] * r["buy_price"], r["value"]) for r in rs
           if r["qty"] is not None and r["buy_price"] is not None and r["value"] is not None]
    invested = round(sum(a for a, _ in inv), 2) if inv else None
    value = round(sum(r["value"] for r in rs if r["value"] is not None), 2) if any(r["value"] is not None for r in rs) else None
    pnl = round(sum(b - a for a, b in inv), 2) if inv else None
    day = [r["day_pnl"] for r in rs if r["day_pnl"] is not None]
    by_ind: dict[str, float] = {}
    for r in rs:
        if r["weight_pct"] is not None:
            k = r["industry"] or "Unknown"
            by_ind[k] = by_ind.get(k, 0.0) + r["weight_pct"]
    hd = data.config().get("holdings_defaults") or {}
    return {
        "as_of": st.as_of(lt) if lt else None, "rows": rs, "inputs": _inputs(), "health_stale": stale,
        "totals": {"count": len(rs), "invested": invested, "value": value, "pnl": pnl,
                   "pnl_pct": round(pnl / sum(a for a, _ in inv) * 100, 2) if inv and sum(a for a, _ in inv) else None,
                   "day_pnl": round(sum(day), 2) if day else None,
                   "danger": sum(1 for r in rs if r["level"] == "danger"),
                   "watch": sum(1 for r in rs if r["level"] == "watch")},
        "by_industry": [{"industry": k, "weight_pct": round(v, 2)} for k, v in sorted(by_ind.items(), key=lambda x: -x[1])],
        "defaults": {"stop_loss_pct": num(hd.get("stop_loss_pct")) or 8.0, "target_pct": num(hd.get("target_pct")) or 20.0},
    }


def validate(rows_in: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    today = today_ist()
    ok, rejected = [], []
    for i, r in enumerate(rows_in):
        sym = str(r.get("symbol") or "").strip().upper()
        reason = None
        qty, buy, sl, tg = (num(r.get(k)) for k in ("qty", "buy_price", "stop_loss_pct", "target_pct"))
        bd = r.get("buy_date")
        if isinstance(bd, str) and bd.strip().lower() in ("", "nat", "nan", "none", "null"):
            bd = None           # "NaT" is what an empty buy date used to come back as: keep the row, no date
        if not sym or sym in ("NAN", "NONE"):
            reason = "empty symbol"
        elif qty is not None and qty < 0:
            reason = "negative quantity"
        elif qty is not None and qty == 0:
            reason = "quantity must be above 0"
        elif qty is not None and not float(qty).is_integer():
            reason = "quantity must be a whole number of shares"
        elif buy is not None and buy <= 0:
            reason = "buy price must be above 0"
        elif sl is not None and not 0 <= sl <= 100:
            reason = "stop-loss % must be between 0 and 100"
        elif tg is not None and tg < 0:
            reason = "target % must not be negative"
        elif bd:
            try:
                d = date.fromisoformat(str(bd)[:10])
                if d > today:
                    reason = "buy date is in the future"
            except ValueError:
                reason = "buy date must be YYYY-MM-DD"
        if reason:
            rejected.append({"index": i, "symbol": sym, "reason": reason})
            continue
        ok.append({"symbol": sym, "qty": qty, "buy_price": buy, "buy_date": str(bd)[:10] if bd else None,
                   "stop_loss_pct": sl, "target_pct": tg})
    lt = data.latest() or {}
    known = set(lt.get("symbols") or []) | set(data.universe()["symbol"]) | set(data.etfs())
    unknown = sorted({r["symbol"] for r in ok} - known)
    return ok, rejected, unknown


def save(rows_ok: list[dict]) -> None:
    df = pd.DataFrame(rows_ok, columns=HOLDING_COLS)
    try:
        save_holdings(df)
    except PermissionError:     # holdings.csv open in Excel: drop save_holdings' temp file, the caller reports it
        try:
            P.holdings.with_suffix(".tmp").unlink(missing_ok=True)
        except OSError:
            pass
        raise


def from_fyers(raw: list[dict]) -> list[dict]:
    out = []
    for h in raw:
        sym = str(h.get("symbol", "")).split(":")[-1].rsplit("-", 1)[0].strip().upper()
        if not sym:
            continue
        # FYERS v3: quantity is the start-of-day quantity, remainingQuantity what is left after today's sales
        rq = num(h.get("remainingQuantity"))
        q, cp = (rq if rq is not None else num(h.get("quantity"))), num(h.get("costPrice"))
        if q == 0:
            continue                # fully sold today
        out.append({"symbol": sym, "qty": q if q is None or not math.isnan(q) else None, "buy_price": cp,
                    "buy_date": None, "stop_loss_pct": None, "target_pct": None})
    return out
