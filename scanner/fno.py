"""F&O positioning from NSE's end-of-day derivatives files - the closest real data to "which side the big players are on".

fao_participant_oi_DDMMYYYY.csv   : open contracts of each participant type - FII, DII, Pro (brokers' own books) and
                                    Client (everyone else) - long and short, in index/stock futures and options
fao_participant_vol_DDMMYYYY.csv  : the same split of the day's traded contracts
BhavCopy_NSE_FO_..._YYYYMMDD.zip  : every future and option: prices, open interest and its change, lot size

NSE names no one: these are totals per participant type, published after the close (about 6-8 PM). Per stock and
index the futures show the day's build-up (price vs open interest) and the options their put-call ratio and the
strikes with the most open interest (call wall / put wall). Positioning, not signals.

  python -m scanner.fno [DAYS]          fetch the last DAYS trading days not stored yet (default 30)
  python intraday_sync.py --fno         the same (19:30 scheduled task)
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from contextlib import contextmanager
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import nse
from .lock import _try_lock, _unlock
from .options import buildup
from .settings import DATA_DIR, ist_now
from .store import _replace

FNO_DIR = DATA_DIR / "fno"
PART_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_{kind}_{d:%d%m%Y}.csv"
FO_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
PART_NAME, FUT_NAME, STATE_NAME, LOCK_NAME = "participants.parquet", "futures.parquet", "state.json", ".write.lock"
DEFAULT_DAYS = 30
FUT_BUILDUP_MIN_PCT = 2.0      # a day's futures OI change under 2% is noise (futures OI moves less than options OI)

CLIENTS = ("fii", "dii", "pro", "client")
PART_COLS = {
    "Future Index Long": "fut_idx_long", "Future Index Short": "fut_idx_short",
    "Future Stock Long": "fut_stk_long", "Future Stock Short": "fut_stk_short",
    "Option Index Call Long": "idx_call_long", "Option Index Put Long": "idx_put_long",
    "Option Index Call Short": "idx_call_short", "Option Index Put Short": "idx_put_short",
    "Option Stock Call Long": "stk_call_long", "Option Stock Put Long": "stk_put_long",
    "Option Stock Call Short": "stk_call_short", "Option Stock Put Short": "stk_put_short",
    "Total Long Contracts": "total_long", "Total Short Contracts": "total_short",
}
FUT_COLS = ["date", "symbol", "kind", "close", "prev_close", "chg_pct", "oi", "oi_chg", "oi_chg_pct", "volume",
            "value_cr", "lot", "underlying", "basis_pct", "buildup", "ce_oi", "pe_oi", "ce_oi_chg", "pe_oi_chg", "pcr",
            "call_wall", "put_wall"]


def folder():
    """data/fno (a module global, so the web API's tests can repoint it)."""
    return FNO_DIR


# --------------------------------------------------------------------------- parsing
def parse_participants(text: str, day: date, kind: str) -> pd.DataFrame:
    """One participant file -> one row per participant type (fii, dii, pro, client), contracts. The TOTAL row is
    dropped (each side's total is the same by construction). Raises ValueError when it is not that day's file."""
    lines = text.lstrip("﻿").splitlines()
    title = lines[0] if lines else ""
    stamp = day.strftime("%b %d, %Y")
    if stamp.replace(" 0", " ") not in title.replace(" 0", " "):
        raise ValueError(f"participant file is not for {day}: {title[:80]!r}")
    df = pd.read_csv(io.StringIO("\n".join(lines[1:])))
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={**PART_COLS, "Client Type": "client"})
    missing = [c for c in PART_COLS.values() if c not in df.columns]
    if missing:
        raise ValueError(f"participant file lacks {missing}")
    df["client"] = df["client"].astype(str).str.strip().str.lower()
    df = df[df["client"].isin(CLIENTS)].copy()
    for c in PART_COLS.values():
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    df.insert(0, "kind", kind)
    df.insert(0, "date", pd.Timestamp(day))
    return df[["date", "kind", "client", *PART_COLS.values()]].reset_index(drop=True)


def parse_fo(content: bytes, day: date) -> pd.DataFrame:
    """NSE's F&O bhavcopy (UDiFF zip) -> one row per underlying with futures (FUT_COLS). Futures OI is in shares,
    volume in contracts; `lot` converts. Options add the put-call ratio and the strikes with the most call / put OI
    in the nearest expiry."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), usecols=["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp",
                                                "ClsPric", "PrvsClsgPric", "UndrlygPric", "OpnIntrst",
                                                "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal", "NewBrdLotQty"])
    dates = pd.to_datetime(df["TradDt"]).dt.date.unique()
    if len(dates) != 1 or dates[0] != day:
        raise ValueError(f"F&O bhavcopy is not for {day}: {list(dates)[:3]}")
    df["XpryDt"] = pd.to_datetime(df["XpryDt"])
    fut = df[df["FinInstrmTp"].isin(["STF", "IDF"])].sort_values(["TckrSymb", "XpryDt"])
    if fut.empty:
        raise ValueError("F&O bhavcopy has no futures")
    near = fut.drop_duplicates("TckrSymb").set_index("TckrSymb")     # nearest expiry's own row: the traded month
    tot = fut.groupby("TckrSymb")[["OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal"]].sum().reindex(near.index)
    out = pd.DataFrame({
        "symbol": near.index.astype(str),
        "kind": np.where(near["FinInstrmTp"] == "IDF", "index", "stock"),
        "close": near["ClsPric"].to_numpy(float), "prev_close": near["PrvsClsgPric"].to_numpy(float),
        "oi": tot["OpnIntrst"].to_numpy(float), "oi_chg": tot["ChngInOpnIntrst"].to_numpy(float),
        "volume": tot["TtlTradgVol"].to_numpy(float), "value_cr": tot["TtlTrfVal"].to_numpy(float) / 1e7,
        "lot": near["NewBrdLotQty"].to_numpy(float), "underlying": near["UndrlygPric"].to_numpy(float),
    })
    out["chg_pct"] = (out["close"] / out["prev_close"].where(out["prev_close"] > 0) - 1) * 100
    prev_oi = out["oi"] - out["oi_chg"]
    out["oi_chg_pct"] = out["oi_chg"] / prev_oi.where(prev_oi > 0) * 100
    out["basis_pct"] = (out["close"] / out["underlying"].where(out["underlying"] > 0) - 1) * 100
    out["buildup"] = buildup(out["close"] - out["prev_close"], out["oi"], out["oi_chg"],
                             min_pct=FUT_BUILDUP_MIN_PCT).to_numpy()

    opt = df[df["FinInstrmTp"].isin(["STO", "IDO"])]
    sides = {}
    for side in ("CE", "PE"):
        o = opt[opt["OptnTp"] == side].groupby("TckrSymb")
        sides[side] = pd.DataFrame({"oi": o["OpnIntrst"].sum(), "oi_chg": o["ChngInOpnIntrst"].sum()})
    nearest = opt["XpryDt"] == opt.groupby("TckrSymb")["XpryDt"].transform("min")
    walls = {}
    for side in ("CE", "PE"):
        o = opt[nearest & (opt["OptnTp"] == side) & (opt["OpnIntrst"] > 0)]
        walls[side] = o.loc[o.groupby("TckrSymb")["OpnIntrst"].idxmax()].set_index("TckrSymb")["StrkPric"]
    s = out["symbol"]
    out["ce_oi"] = s.map(sides["CE"]["oi"]).to_numpy(float)
    out["pe_oi"] = s.map(sides["PE"]["oi"]).to_numpy(float)
    out["ce_oi_chg"] = s.map(sides["CE"]["oi_chg"]).to_numpy(float)
    out["pe_oi_chg"] = s.map(sides["PE"]["oi_chg"]).to_numpy(float)
    out["pcr"] = out["pe_oi"] / out["ce_oi"].where(out["ce_oi"] > 0)
    out["call_wall"] = s.map(walls["CE"]).to_numpy(float)
    out["put_wall"] = s.map(walls["PE"]).to_numpy(float)
    out.insert(0, "date", pd.Timestamp(day))
    return out[FUT_COLS]


# --------------------------------------------------------------------------- storage
@contextmanager
def _write_lock(timeout: float = 30.0):
    folder().mkdir(parents=True, exist_ok=True)
    fh = open(folder() / LOCK_NAME, "a+")
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(fh):
            if time.monotonic() > deadline:
                raise TimeoutError("F&O files are busy")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fh)
    finally:
        fh.close()


def _write_parquet(df: pd.DataFrame, path) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    _replace(tmp, path)


def load_participants() -> pd.DataFrame:
    p = folder() / PART_NAME
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=["date", "kind", "client", *PART_COLS.values()])


def load_futures() -> pd.DataFrame:
    p = folder() / FUT_NAME
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=FUT_COLS)


def load_state() -> dict:
    try:
        return json.loads((folder() / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _append(path, new: pd.DataFrame, day: date) -> None:
    old = pd.read_parquet(path) if path.exists() else None
    if old is not None:
        old = old[pd.to_datetime(old["date"]).dt.date != day]
    _write_parquet(new if old is None or old.empty else pd.concat([old, new], ignore_index=True), path)


def _trading_days(n: int, until: date) -> list[date]:
    from .intraday.fyers_sync import is_trading_day
    out, d = [], until
    while len(out) < n and (until - d).days < n * 2 + 15:
        if is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def refresh(days: int = DEFAULT_DAYS, log=print, today: date | None = None) -> dict:
    """Fetch the participant files and the F&O bhavcopy for the last `days` trading days not stored yet. A day whose
    files are not out yet (today before ~8 PM) is skipped and tried on the next run. Never raises for NSE problems."""
    t0 = time.monotonic()
    today = today or ist_now().date()
    have = set(pd.to_datetime(load_futures()["date"]).dt.date) & set(pd.to_datetime(load_participants()["date"]).dt.date)
    rep = {"started_at": ist_now().isoformat(timespec="seconds"), "added": [], "pending": [], "errors": []}
    for d in [d for d in _trading_days(days, today) if d not in have]:
        try:
            parts = []
            for kind in ("oi", "vol"):
                code, body = nse._get_bytes(PART_URL.format(kind=kind, d=d))
                if code != 200:
                    raise FileNotFoundError(f"participant {kind} file: HTTP {code}")
                parts.append(parse_participants(body.decode("utf-8", "replace"), d, kind))
            code, body = nse._get_bytes(FO_URL.format(d=d))
            if code != 200:
                raise FileNotFoundError(f"F&O bhavcopy: HTTP {code}")
            fut = parse_fo(body, d)
        except FileNotFoundError as e:
            (rep["pending"] if d == today else rep["errors"]).append(f"{d}: {e}")
            continue
        except Exception as e:          # a malformed file must not stop the other days
            rep["errors"].append(f"{d}: {type(e).__name__}: {e}")
            continue
        with _write_lock():
            _append(folder() / PART_NAME, pd.concat(parts, ignore_index=True), d)
            _append(folder() / FUT_NAME, fut, d)
        rep["added"].append(d.isoformat())
        log(f"  F&O {d}: {len(fut)} underlyings, participant positions stored")
    rep["elapsed_s"] = round(time.monotonic() - t0, 1)
    try:
        with _write_lock():
            tmp = folder() / f"{STATE_NAME}.{os.getpid()}.tmp"
            tmp.write_text(json.dumps({"last_refresh": rep}, indent=1), encoding="utf-8")
            _replace(tmp, folder() / STATE_NAME)
    except (OSError, TimeoutError) as e:
        rep["errors"].append(f"status not saved: {type(e).__name__}")
    return rep


# --------------------------------------------------------------------------- views
def positions(part: pd.DataFrame, days: int = 20) -> dict:
    """Per participant type, per day (newest last): index futures long / short / net / long share, the change in net
    since the day before, and net index calls and puts (long - short contracts). Open interest only."""
    oi = part[part["kind"] == "oi"].copy()
    if oi.empty:
        return {"dates": [], "clients": {}}
    oi["date"] = pd.to_datetime(oi["date"])
    dates = sorted(oi["date"].unique())[-days - 1:]               # one more day for the first change
    out = {}
    for c in CLIENTS:
        x = oi[oi["client"] == c].set_index("date").reindex(dates)
        net = x["fut_idx_long"] - x["fut_idx_short"]
        tot = x["fut_idx_long"] + x["fut_idx_short"]
        out[c] = {
            "fut_long": x["fut_idx_long"], "fut_short": x["fut_idx_short"], "fut_net": net,
            "fut_net_chg": net.diff(), "fut_long_pct": x["fut_idx_long"] / tot.where(tot > 0) * 100,
            "call_net": x["idx_call_long"] - x["idx_call_short"], "put_net": x["idx_put_long"] - x["idx_put_short"],
            "stk_fut_net": x["fut_stk_long"] - x["fut_stk_short"],
        }
    keep = dates[1:] if len(dates) > days else dates
    return {"dates": [pd.Timestamp(d).date().isoformat() for d in keep],
            "clients": {c: {k: [None if pd.isna(v) else float(v) for v in s.reindex(keep)] for k, s in m.items()}
                        for c, m in out.items()}}


def day_futures(fut: pd.DataFrame, day: date | None = None) -> tuple[date | None, pd.DataFrame]:
    """The futures table of `day` (default: the newest stored day)."""
    if fut.empty:
        return None, fut
    d = pd.to_datetime(fut["date"]).dt.date
    day = day or d.max()
    return day, fut[d == day].reset_index(drop=True)


if __name__ == "__main__":
    r = refresh(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DAYS)
    print(json.dumps(r, indent=1))
