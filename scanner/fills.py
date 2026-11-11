"""Your real fills on FYERS, kept on this PC (data/fills.jsonl): one line per filled order, written by the Orders page
(web/api/services/orders_svc.py, from the order book) and by the live service's order socket (intraday/order_feed.py),
whichever sees the fill first. FYERS' order book only covers today, so this file is what remembers your trades for the
trade coach (round trips matched first-in, first-out per symbol). Nothing here is ever sent anywhere.
"""
from __future__ import annotations

import json
from pathlib import Path

from .intraday.data import FileLock
from .settings import DATA_DIR

FILE_NAME = "fills.jsonl"


def path(data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / FILE_NAME


def read(data_dir: Path | None = None) -> list[dict]:
    p = path(data_dir)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue                                   # a torn line: skip it
    return out


def record(rows: list[dict], data_dir: Path | None = None) -> int:
    """Append fills not seen before (by FYERS order id); returns how many were new. Each row: id, symbol, side (BUY /
    SELL), qty, price, time, product, and optionally strategy_key, ref_price, stop, source."""
    rows = [r for r in rows if r.get("id") and r.get("qty") and r.get("price")]
    if not rows:
        return 0
    p = path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(p.with_name(".fills.lock"))
    if not lock.acquire(timeout=5):
        return 0                                       # the other writer has it: it will be recorded next time
    try:
        seen = {str(r.get("id")) for r in read(data_dir)}
        new = [r for r in rows if str(r["id"]) not in seen]
        if new:
            with open(p, "a", encoding="utf-8") as f:
                for r in new:
                    f.write(json.dumps(r, separators=(",", ":"), default=str) + "\n")
        return len(new)
    finally:
        lock.release()


def round_trips(fills: list[dict]) -> tuple[list[dict], list[dict]]:
    """Closed trades (buys matched to later sells first-in, first-out per symbol and product) and what is still
    open. A sell with no earlier buy here (shares bought before this log existed, or an intraday short) is skipped."""
    lots: dict[tuple, list[dict]] = {}
    closed: list[dict] = []
    for f in sorted(fills, key=lambda x: str(x.get("time") or "")):
        key = (f.get("symbol"), f.get("product") or "CNC")
        qty, px = float(f["qty"]), float(f["price"])
        if f.get("side") == "BUY":
            lots.setdefault(key, []).append({"qty": qty, "price": px, "time": f.get("time"),
                                             "strategy_key": f.get("strategy_key"), "stop": f.get("stop")})
            continue
        q = lots.get(key) or []
        while qty > 1e-9 and q:
            lot = q[0]
            take = min(qty, lot["qty"])
            closed.append({"symbol": key[0], "product": key[1], "qty": take, "entry": lot["price"], "exit": px,
                           "entry_time": lot["time"], "exit_time": f.get("time"), "strategy_key": lot.get("strategy_key"),
                           "stop": lot.get("stop"), "pnl": round((px - lot["price"]) * take, 2),
                           "ret_pct": round((px / lot["price"] - 1) * 100, 2) if lot["price"] else None})
            lot["qty"] -= take
            qty -= take
            if lot["qty"] <= 1e-9:
                q.pop(0)
    still = [{"symbol": k[0], "product": k[1], **lot} for k, q in lots.items() for lot in q if lot["qty"] > 1e-9]
    return closed, still
