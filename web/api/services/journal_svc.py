"""Trade journal (GET /api/journal, PUT /api/journal/{id}): every trade you made in one list, with your notes, and the
statistics that show what works for you.

Trades come from three places, each tagged with its source:
  * real: Quant Desk's recorded FYERS fills, buys matched to later sells first-in first-out (scanner/fills.py);
    charges estimated with the cost model (FYERS' contract notes have the exact ones);
  * practice: the practice account on live prices (data/sim_account.json);
  * replay: finished Replay sessions (data/replay_log.jsonl), P&L after charges.
Your notes are kept apart (data/journal.json) by a trade id made from the trade itself, so they survive restarts.

Statistics: win rate, average win and loss, expectancy (the average trade), profit factor, and the same split by
setup tag, mistake, hour and weekday of entry, holding time and side. Excursions: how far the price went against the
trade (MAE) and in its favour (MFE) while it was open, from the daily store or the stored 5-minute bars; winners'
MAE says how much room a stop needs, MFE against the result says how much of the move was kept.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict
from statistics import mean

import pandas as pd

from scanner import fills
from scanner.costs import CostModel
from scanner.intraday import data as idata

from . import data, replay_svc, sim_svc
from ..errors import ApiException
from ..paths import P
from ..util import now_ist

FILE = "journal.json"
MISTAKES = ("Chased the entry", "No stop", "Moved the stop away", "Sold too early", "Held a loser too long",
            "Position too big", "Against the trend", "Traded on news / tips", "Revenge trade", "Broke my plan")
MAX_IMAGE = 600_000                  # a pasted chart screenshot, as a data URL
_lock = threading.Lock()


def _path():
    return P.data / FILE


def notes() -> dict:
    try:
        v = json.loads(_path().read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def trade_id(t: dict) -> str:
    key = "|".join(str(t.get(k)) for k in ("source", "symbol", "side", "qty", "entry", "exit", "opened", "closed"))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _ts(x) -> pd.Timestamp | None:
    try:
        t = pd.Timestamp(x)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize(None) if t.tzinfo else t


def gather() -> list[dict]:
    """All trades, newest first, without notes."""
    out: list[dict] = []
    cm = CostModel.from_config(data.config().get("costs"))
    try:
        closed, _ = fills.round_trips(fills.read())
    except Exception:
        closed = []
    for t in closed:
        buy_v, sell_v = t["entry"] * t["qty"], t["exit"] * t["qty"]
        ch = cm.buy_cost(buy_v) + cm.sell_cost(sell_v)
        out.append({"source": "real", "symbol": t["symbol"], "side": "LONG", "qty": t["qty"], "entry": t["entry"],
                    "exit": t["exit"], "opened": t.get("entry_time"), "closed": t.get("exit_time"),
                    "pnl": round(t["pnl"] - ch, 2), "charges": round(ch, 2), "reason": t.get("strategy_key") or "",
                    "stop": t.get("stop"), "tf": None})
    try:
        st = sim_svc._load() if sim_svc._path().exists() else {"trades": []}
    except Exception:
        st = {"trades": []}
    for t in st.get("trades") or []:
        out.append({"source": "practice", "symbol": t["symbol"], "side": t["side"], "qty": t["qty"], "entry": t["entry"],
                    "exit": t["exit"], "opened": t.get("opened"), "closed": t.get("closed"),
                    "pnl": round(t["pnl"] - (t.get("charges") or 0), 2), "charges": t.get("charges"),
                    "reason": t.get("reason") or "", "stop": None, "tf": None})
    try:
        rows = replay_svc.log_rows()
    except Exception:
        rows = []
    for r in rows:
        for t in r.get("trades") or []:
            out.append({"source": "replay", "symbol": r["symbol"], "side": t["side"], "qty": t["qty"], "entry": t["entry"],
                        "exit": t["exit"], "opened": t.get("entry_t"), "closed": t.get("exit_t"), "pnl": t["net"],
                        "charges": t.get("charges"), "reason": t.get("reason") or "", "stop": t.get("stop"),
                        "tf": r.get("tf"), "r": t.get("r")})
    for t in out:
        t["id"] = trade_id(t)
        o, c = _ts(t["opened"]), _ts(t["closed"])
        t["hold_days"] = (c.normalize() - o.normalize()).days if o is not None and c is not None else None
        t["ret_pct"] = round(t["pnl"] / (t["entry"] * t["qty"]) * 100, 2) if t["entry"] and t["qty"] else None
    out.sort(key=lambda t: str(t.get("closed") or ""), reverse=True)
    return out


def excursion(t: dict, close_store: dict | None = None) -> tuple[float | None, float | None]:
    """(MAE %, MFE %) of the entry price while the trade was open: daily bars for multi-day trades, the stored
    5-minute bars for a trade opened and closed on one day. None when the bars aren't there."""
    o, c = _ts(t.get("opened")), _ts(t.get("closed"))
    if o is None or c is None or not t.get("entry"):
        return None, None
    sym, entry, long = t["symbol"], float(t["entry"]), t["side"] == "LONG"
    hi = lo = None
    if o.normalize() == c.normalize():
        try:
            b = idata.IntradayStore(P.intraday_bars).load("5m", [sym], start=o.date(), end=c.date())
            b = b[(b["ts"] >= o.floor("5min")) & (b["ts"] <= c)]
            if len(b):
                hi, lo = float(b["high"].max()), float(b["low"].min())
        except Exception:
            pass
    else:
        s = close_store or {}
        try:
            h = s["high"][sym].loc[o.normalize():c.normalize()].dropna()
            l_ = s["low"][sym].loc[o.normalize():c.normalize()].dropna()
            if len(h) and len(l_):
                hi, lo = float(h.max()), float(l_.min())
        except Exception:
            pass
    if hi is None or lo is None:
        return None, None
    fav, adv = ((hi / entry - 1) * 100, (lo / entry - 1) * 100) if long else ((1 - lo / entry) * 100, (1 - hi / entry) * 100)
    return round(min(adv, 0.0), 2), round(max(fav, 0.0), 2)


def _summary(ts: list[dict]) -> dict:
    n = len(ts)
    if not n:
        return {"trades": 0}
    pnl = [t["pnl"] for t in ts]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    gw, gl = sum(wins), -sum(losses)
    return {"trades": n, "win_rate": round(len(wins) / n * 100, 1), "total": round(sum(pnl), 2),
            "avg_win": round(mean(wins), 2) if wins else None, "avg_loss": round(mean(losses), 2) if losses else None,
            "expectancy": round(sum(pnl) / n, 2), "profit_factor": round(gw / gl, 2) if gl > 0 else None,
            "best": round(max(pnl), 2), "worst": round(min(pnl), 2)}


def _by(ts: list[dict], key) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for t in ts:
        for k in key(t):
            g[k].append(t)
    return sorted(({"key": k, **_summary(v)} for k, v in g.items()), key=lambda x: -x["trades"])


def _hold_bucket(t: dict) -> list[str]:
    d = t.get("hold_days")
    if d is None:
        return []
    return ["Same day" if d == 0 else "1-5 days" if d <= 5 else "6-20 days" if d <= 20 else "Over 20 days"]


def stats(ts: list[dict]) -> dict:
    wd = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    def hour(t):
        o = _ts(t.get("opened"))
        return [f"{o.hour:02d}:00"] if o is not None and (o.hour, o.minute) != (0, 0) else []

    def weekday(t):
        o = _ts(t.get("opened"))
        return [wd[o.weekday()]] if o is not None else []

    wins = [t for t in ts if t["pnl"] > 0 and t.get("mae_pct") is not None]
    losers = [t for t in ts if t["pnl"] <= 0 and t.get("mae_pct") is not None]
    kept = [t["ret_pct"] / t["mfe_pct"] * 100 for t in ts if t.get("mfe_pct") and t["mfe_pct"] > 0.1 and t.get("ret_pct") is not None and t["pnl"] > 0]
    mistakes = _by([t for t in ts if t.get("mistakes")], lambda t: t["mistakes"])
    return {
        "overall": _summary(ts),
        "by_source": _by(ts, lambda t: [t["source"]]),
        "by_setup": _by(ts, lambda t: [t.get("setup") or "No setup tag"]),
        "by_tag": _by([t for t in ts if t.get("tags")], lambda t: t["tags"]),
        "by_mistake": sorted(mistakes, key=lambda x: x.get("total") or 0),
        "by_hour": sorted(_by(ts, hour), key=lambda x: x["key"]),
        "by_weekday": sorted(_by(ts, weekday), key=lambda x: wd.index(x["key"])),
        "by_hold": _by(ts, _hold_bucket), "by_side": _by(ts, lambda t: [t["side"]]),
        "excursion": {"winners_mae_pct": round(mean(t["mae_pct"] for t in wins), 2) if wins else None,
                      "losers_mae_pct": round(mean(t["mae_pct"] for t in losers), 2) if losers else None,
                      "winners_worst_mae_pct": round(min(t["mae_pct"] for t in wins), 2) if wins else None,
                      "kept_of_best_pct": round(mean(kept), 1) if kept else None, "with_bars": len(wins) + len(losers)},
        "rated": _by([t for t in ts if t.get("rating")], lambda t: [f"{t['rating']} star"]),
    }


def view(source: str = "all") -> dict:
    every = gather()
    ts = every if source == "all" else [t for t in every if t["source"] == source]
    nt = notes()
    try:
        store = data.store()
    except Exception:
        store = None
    for t in ts:
        n = nt.get(t["id"]) or {}
        t.update(setup=n.get("setup") or "", tags=n.get("tags") or [], mistakes=n.get("mistakes") or [],
                 notes=n.get("notes") or "", rating=n.get("rating"), has_image=bool(n.get("image")))
        t["mae_pct"], t["mfe_pct"] = excursion(t, store)
    setups = sorted({t["setup"] for t in ts if t["setup"]})
    tags = sorted({x for t in ts for x in t["tags"]})
    return {"trades": ts, "stats": stats(ts), "setups": setups, "tags": tags, "mistakes": list(MISTAKES),
            "counts": {s: sum(1 for t in every if t["source"] == s) for s in ("real", "practice", "replay")},
            "as_of": now_ist().isoformat(timespec="seconds"),
            "note": "Real-trade charges are estimated with the cost model; your contract notes have the exact ones."}


def save_note(tid: str, body: dict) -> dict:
    if tid not in {t["id"] for t in gather()}:
        raise ApiException("NOT_FOUND", "No trade with that id.")
    img = body.get("image")
    if img and (not str(img).startswith("data:image/") or len(img) > MAX_IMAGE):
        raise ApiException("VALIDATION", "The screenshot must be an image under about 450 KB.")
    with _lock:
        nt = notes()
        cur = nt.get(tid) or {}
        for k in ("setup", "tags", "mistakes", "notes", "rating"):
            if k in body and body[k] is not None:
                cur[k] = body[k]
        if "image" in body:
            if body["image"]:
                cur["image"] = body["image"]
            else:
                cur.pop("image", None)
        cur["updated"] = now_ist().isoformat(timespec="seconds")
        nt[tid] = cur
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(json.dumps(nt, indent=1), encoding="utf-8")
        tmp.replace(_path())
    return {k: v for k, v in cur.items() if k != "image"} | {"has_image": bool(cur.get("image"))}


def image(tid: str) -> str | None:
    return (notes().get(tid) or {}).get("image")
