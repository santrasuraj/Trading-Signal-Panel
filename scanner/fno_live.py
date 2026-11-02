"""Big trades live in index futures and options, from the FYERS WebSocket (the live service, intraday/live.py).

At the start of the session the live service subscribes, besides its stocks, to the nearest futures of
`live_fno.futures` and the nearest-expiry calls and puts of `live_fno.options` within `strikes_each_side` strikes of the
money (the spot from the latest stored option chain). FYERS allows 100 symbols in all, so these slots come off the
stocks (default 2 futures + 18 NIFTY options = 20; stocks keep 80).

Every single trade of `future_print_cr` (notional) or `option_print_lakh` (premium) or more is kept, with the side
that most likely started it: at or above the best ask = a buyer lifted the offer, at or below the best bid = a seller
hit the bid (the tick rule; between the two it stays unknown). Who traded, and whether it opened or closed a position,
cannot be known - NSE never shows names live.

Instruments come from FYERS' public symbol list (public.fyers.in/sym_details/NSE_FO.csv: ticker, lot size, expiry,
strike, option type; cached once a day). FYERS' tick quantity for derivatives is read in units or lots, whichever it
is: an F&O trade is always a whole number of lots, so a quantity that is not a multiple of the lot size is lots.
"""
from __future__ import annotations

import io
import json
import time
from datetime import date, datetime

import pandas as pd

from .settings import DATA_DIR, IST, ist_now

MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
MASTER_FILE = DATA_DIR / "intraday" / "fyers_nse_fo.csv"
LIVE_DIR = DATA_DIR / "intraday" / "live"
MASTER_COLS = {1: "name", 2: "itype", 3: "lot", 8: "expiry_epoch", 9: "ticker", 13: "underlying", 15: "strike", 16: "opt"}
DEFAULTS = {"futures": ["NIFTY", "BANKNIFTY"], "options": ["NIFTY"], "strikes_each_side": 4,
            "future_print_cr": 5.0, "option_print_lakh": 25.0}
MAX_SLOTS = 40               # never more than 40 of FYERS' 100 live symbols for F&O
FRESH_SECONDS = 120          # the feed counts as live while its book file is this recent
RECENT_PRINTS = 40


def settings(cfg: dict | None = None) -> dict:
    """config.yaml `live_fno:` over DEFAULTS, validated (bad values fall back to the default)."""
    raw = (cfg or {}).get("live_fno") or {}
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    for key in ("futures", "options"):
        v = raw.get(key)
        if isinstance(v, (list, tuple)):
            out[key] = [str(s).strip().upper() for s in v if str(s).strip()]
    for key, lo, hi, cast in (("strikes_each_side", 0, 15, int), ("future_print_cr", 0.1, 1000.0, float),
                              ("option_print_lakh", 1.0, 10000.0, float)):
        try:
            out[key] = min(max(cast(raw.get(key, out[key])), lo), hi)
        except (TypeError, ValueError):
            pass
    return out


def lot_count(qty: float, lot: float) -> float:
    """Lots in a trade whose quantity FYERS may give in units or in lots (see the module note)."""
    if lot > 0 and qty >= lot and abs(qty / lot - round(qty / lot)) < 1e-9:
        return qty / lot
    return qty


# --------------------------------------------------------------------------- instruments
def parse_master(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), header=None, low_memory=False, usecols=list(MASTER_COLS))
    df = df.rename(columns=MASTER_COLS)
    df["expiry"] = (pd.to_datetime(df["expiry_epoch"], unit="s", utc=True).dt.tz_convert(IST).dt.date)
    df["opt"] = df["opt"].astype(str).str.upper()
    return df[["ticker", "name", "itype", "underlying", "expiry", "strike", "opt", "lot"]]


def load_master(log=print, today: date | None = None) -> pd.DataFrame:
    """FYERS' F&O symbol list: today's cached copy, else downloaded (15 MB), else an older cached copy."""
    import requests
    today = today or ist_now().date()
    fresh = (MASTER_FILE.exists()
             and datetime.fromtimestamp(MASTER_FILE.stat().st_mtime, IST).date() == today)
    if not fresh:
        try:
            r = requests.get(MASTER_URL, timeout=60)
            if r.status_code == 200 and len(r.content) > 1000:
                MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = MASTER_FILE.with_suffix(".tmp")
                tmp.write_bytes(r.content)
                tmp.replace(MASTER_FILE)
            else:
                log(f"FYERS symbol list: HTTP {r.status_code}")
        except Exception as e:
            log(f"FYERS symbol list not downloaded ({type(e).__name__}) - using the cached copy if any")
    if not MASTER_FILE.exists():
        return pd.DataFrame(columns=["ticker", "name", "itype", "underlying", "expiry", "strike", "opt", "lot"])
    return parse_master(MASTER_FILE.read_text(encoding="utf-8", errors="replace"))


def pick(master: pd.DataFrame, st: dict, spots: dict[str, float], today: date) -> list[dict]:
    """The futures and options to stream: the nearest future of each `futures` underlying, and for each `options`
    underlying with a known spot, its nearest-expiry calls and puts within `strikes_each_side` strikes of the money."""
    m = master[master["expiry"] >= today]
    out: list[dict] = []
    for u in st["futures"]:
        f = m[(m["underlying"] == u) & (m["opt"] == "XX")].sort_values("expiry")
        if len(f):
            r = f.iloc[0]
            out.append({"ticker": r["ticker"], "underlying": u, "kind": "fut", "strike": None,
                        "expiry": r["expiry"].isoformat(), "lot": int(r["lot"])})
    for u in st["options"]:
        spot = spots.get(u)
        o = m[(m["underlying"] == u) & m["opt"].isin(["CE", "PE"])]
        if not spot or o.empty:
            continue
        o = o[o["expiry"] == o["expiry"].min()]
        strikes = sorted(o["strike"].unique())
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        keep = set(strikes[max(0, atm - st["strikes_each_side"]): atm + st["strikes_each_side"] + 1])
        for r in o[o["strike"].isin(keep)].sort_values(["strike", "opt"]).itertuples(index=False):
            out.append({"ticker": r.ticker, "underlying": u, "kind": r.opt.lower(), "strike": float(r.strike),
                        "expiry": r.expiry.isoformat(), "lot": int(r.lot)})
    return out[:MAX_SLOTS]


def spots() -> dict[str, float]:
    """The latest spot of each option-chain underlying (data/options/latest.json; the live job starts before the
    open, so this is usually the last close)."""
    from . import options
    out: dict[str, tuple[str, float]] = {}
    for c in (options.load_latest().get("chains") or {}).values():
        sym, t, s = c.get("symbol"), str(c.get("time") or ""), c.get("spot")
        if sym and s and (sym not in out or t > out[sym][0]):
            out[sym] = (t, float(s))
    return {k: v for k, (_, v) in out.items()}


def instruments(cfg: dict | None = None, log=print) -> list[dict]:
    """What the live service should stream for F&O today (empty when nothing is configured or the list is missing)."""
    st = settings(cfg)
    if not st["futures"] and not st["options"]:
        return []
    master = load_master(log)
    if master.empty:
        log("No FYERS symbol list - no live F&O trades today")
        return []
    sp = spots()
    missing = [u for u in st["options"] if u not in sp]
    if missing:
        log(f"No stored option chain for {', '.join(missing)} - their options are not streamed "
            "(fetch the chain on the Options page once)")
    return pick(master, st, sp, ist_now().date())


# --------------------------------------------------------------------------- recording (inside the live service)
def prints_file(day: date, folder=None):
    return (folder or LIVE_DIR) / f"fno_prints_{day:%Y%m%d}.parquet"


def book_file(folder=None):
    return (folder or LIVE_DIR) / "fno_book.json"


class FnoRecorder:
    """Large futures and options trades and the latest book totals, from FYERS SymbolUpdate ticks (fields read
    defensively: a tick without trade size or book simply adds nothing)."""

    def __init__(self, instruments: list[dict], st: dict | None = None):
        st = st or settings()
        self.info = {i["ticker"]: i for i in instruments}
        self.min_fut = st["future_print_cr"] * 1e7
        self.min_opt = st["option_print_lakh"] * 1e5
        self.prints: list[dict] = []
        self.book: dict[str, dict] = {}

    def wants(self, ticker) -> bool:
        return ticker in self.info

    def on_tick(self, msg: dict) -> None:
        info = self.info.get(msg.get("symbol"))
        ltp = float(msg.get("ltp") or 0)
        if info is None or ltp <= 0:
            return
        lots = lot_count(float(msg.get("last_traded_qty") or 0), info["lot"])
        value = lots * info["lot"] * ltp
        t = msg.get("last_traded_time") or msg.get("exch_feed_time")
        if lots > 0 and t and value >= (self.min_fut if info["kind"] == "fut" else self.min_opt):
            bid, ask = float(msg.get("bid_price") or 0), float(msg.get("ask_price") or 0)
            side = "BUY" if ask and ltp >= ask else "SELL" if bid and ltp <= bid else None
            self.prints.append({"ts": pd.Timestamp(int(t), unit="s") + pd.Timedelta(hours=5, minutes=30),
                                "ticker": info["ticker"], "underlying": info["underlying"], "kind": info["kind"],
                                "strike": info["strike"], "expiry": info["expiry"], "price": ltp, "lots": lots,
                                "value": value, "side": side})
        b = self.book.setdefault(info["ticker"], {})
        b["ltp"] = ltp
        for src, dst in (("tot_buy_qty", "buy_qty"), ("tot_sell_qty", "sell_qty"), ("vol_traded_today", "volume")):
            if msg.get(src) is not None:
                b[dst] = float(msg[src])

    def flush(self, day: date, folder=None) -> None:
        folder = folder or LIVE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        if self.prints:
            path = prints_file(day, folder)
            new = pd.DataFrame(self.prints)
            old = pd.read_parquet(path) if path.exists() else new.iloc[0:0]
            tmp = path.with_suffix(".tmp")
            pd.concat([old, new], ignore_index=True).to_parquet(tmp, index=False)
            tmp.replace(path)
            self.prints = []
        tmp = book_file(folder).with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": ist_now().isoformat(timespec="seconds"), "day": day.isoformat(),
                                   "instruments": list(self.info.values()), "book": self.book}), encoding="utf-8")
        tmp.replace(book_file(folder))


# --------------------------------------------------------------------------- the page
def summary(folder=None, now: datetime | None = None) -> dict:
    """Today's (else the newest day's) large trades: per instrument totals by side, and the latest trades."""
    folder = folder or LIVE_DIR
    now = now or ist_now()
    try:
        bk = json.loads(book_file(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bk = {}
    files = sorted(folder.glob("fno_prints_*.parquet")) if folder.exists() else []
    day = bk.get("day") or (files[-1].stem.split("_")[-1] if files else None)
    if day and len(day) == 8:
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    path = prints_file(date.fromisoformat(day), folder) if day else None
    pr = pd.read_parquet(path) if path is not None and path.exists() else pd.DataFrame(
        columns=["ts", "ticker", "underlying", "kind", "strike", "expiry", "price", "lots", "value", "side"])
    try:
        age = (now - datetime.fromisoformat(bk["at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    book = bk.get("book") or {}
    insts = []
    for i in bk.get("instruments") or []:
        p = pr[pr["ticker"] == i["ticker"]]
        val = lambda s: float(p.loc[p["side"] == s, "value"].sum()) / 1e7     # noqa: E731
        unknown = float(p.loc[p["side"].isna(), "value"].sum()) / 1e7
        b = book.get(i["ticker"]) or {}
        insts.append({**i, "prints": int(len(p)), "buy_cr": round(val("BUY"), 2), "sell_cr": round(val("SELL"), 2),
                      "unknown_cr": round(unknown, 2), "net_cr": round(val("BUY") - val("SELL"), 2),
                      "ltp": b.get("ltp"), "buy_qty": b.get("buy_qty"), "sell_qty": b.get("sell_qty"),
                      "volume": b.get("volume")})
    recent = pr.sort_values("ts", ascending=False).head(RECENT_PRINTS) if len(pr) else pr
    return {"date": day, "updated_at": bk.get("at"), "live": age is not None and 0 <= age <= FRESH_SECONDS,
            "instruments": insts,
            "recent": [{"ts": pd.Timestamp(r.ts).isoformat(), "ticker": r.ticker, "underlying": r.underlying,
                        "kind": r.kind, "strike": None if pd.isna(r.strike) else float(r.strike), "expiry": r.expiry,
                        "price": float(r.price), "lots": float(r.lots), "value_cr": round(float(r.value) / 1e7, 3),
                        "side": r.side if isinstance(r.side, str) else None}
                       for r in recent.itertuples(index=False)]}


if __name__ == "__main__":
    t0 = time.monotonic()
    for i in instruments():
        print(i)
    print(f"({time.monotonic() - t0:.1f} s)")
