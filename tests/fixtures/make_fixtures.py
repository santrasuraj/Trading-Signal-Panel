"""Rebuild tests/fixtures/root from real result files (read-only on data/).

    python tests/fixtures/make_fixtures.py SCAN_DIR [DATA_DIR]

SCAN_DIR holds the output of one full scan run by the current daily.py (latest.json, curves.parquet,
trades.parquet, screener.parquet) - e.g. a sandboxed run whose outputs were redirected away from data/.
DATA_DIR (default: ./data) provides the price store, NSE caches, intraday.json, journal and logs.
The price store and index history are cut down (subset of symbols, last ~420 days) to keep the fixtures small.
The real 09:18 scan of 23 Oct 2026 (older schema, no B1-B10 fields) is kept as legacy_latest.json.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "root"
DAYS = 420


def main() -> None:
    scan = Path(sys.argv[1])
    data = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data"
    if OUT.exists():
        shutil.rmtree(OUT)
    res, nse, store_dir = OUT / "data" / "results", OUT / "data" / "nse", OUT / "data" / "history" / "store"
    for d in (res, nse, store_dir, OUT / "data" / "logs"):
        d.mkdir(parents=True)
    for f in ("latest.json", "curves.parquet", "trades.parquet", "screener.parquet"):
        shutil.copy2(scan / f, res / f)
    lt = json.loads((scan / "latest.json").read_text(encoding="utf-8"))
    shutil.copy2(scan / "latest.json", res / f"scan_{pd.Timestamp(lt['generated_at']):%Y%m%d_%H%M}.json")
    shutil.copy2(data / "results" / "intraday.json", res / "intraday.json")
    shutil.copy2(data / "results" / "scan_20261023_0918.json", HERE / "legacy_latest.json")
    (res / "status.json").write_text(json.dumps({"state": "done", "message": "Done in 205.2s", "progress": 1.0,
                                                 "started": 1792734489.0}), encoding="utf-8")
    for pat in ("events_20261023.json", "holidays_2026.json", "results_202609.json", "results_202610.json",
                "results_202611.json"):
        shutil.copy2(data / "nse" / pat, nse / pat)
    shutil.copy2(data / "universe_nifty500.csv", OUT / "data" / "universe_nifty500.csv")
    shutil.copy2(data / "journal.sqlite", OUT / "data" / "journal.sqlite")
    shutil.copy2(data / "logs" / "scanner.log", OUT / "data" / "logs" / "scanner.log")
    shutil.copy2(ROOT / "config.yaml", OUT / "config.yaml")
    (OUT / "holdings.csv").write_text("symbol,qty,buy_price,buy_date,stop_loss_pct,target_pct\n"
                                      "IGIL,100,300,2026-09-01,,\nTCS,10,3000,,8,20\n", encoding="utf-8")

    # ---- symbols the fixtures need
    syms = {"NIFTY50", "NIFTY500", "INDIAVIX", "IGIL", "TCS", "STLTECH", "CUPID"}
    syms |= {str(e).upper() for e in ["NIFTYBEES", "JUNIORBEES", "BANKBEES", "GOLDBEES", "MON100"]}
    for s in lt["strategies"]:
        syms |= {p["symbol"] for p in s["positions"]} | {a["symbol"] for a in s["actions"]}
        syms |= {r["symbol"] for r in s["ranking"][:5]}
    for k in ("gainers", "losers", "volume_spikes"):
        syms |= {r["symbol"] for r in lt[k][:5]}
    import sqlite3
    with sqlite3.connect(data / "journal.sqlite") as con:
        syms |= {r[0] for r in con.execute("SELECT DISTINCT symbol FROM positions")}
        syms |= {r[0] for r in con.execute("SELECT DISTINCT symbol FROM orders")}

    # ---- price store subset (same .npy generation format as scanner/store.py)
    src = data / "history" / "store"
    gen = src / (src / "CURRENT").read_text(encoding="utf-8").strip()
    dates = np.load(gen / "dates.npy")
    cols = json.loads((gen / "symbols.json").read_text(encoding="utf-8"))
    keep = [i for i, c in enumerate(cols) if c in syms]
    g = store_dir / "gen_fixture"
    g.mkdir()
    np.save(g / "dates.npy", dates[-DAYS:])
    (g / "symbols.json").write_text(json.dumps([cols[i] for i in keep]), encoding="utf-8")
    for f in ("open", "high", "low", "close", "volume", "deliv_pct"):
        arr = np.load(gen / f"{f}.npy")
        np.save(g / f"{f}.npy", arr[-DAYS:, keep])
    (store_dir / "CURRENT").write_text("gen_fixture", encoding="utf-8")
    meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    meta["symbols"] = {k: v for k, v in meta.get("symbols", {}).items() if k in syms}
    (store_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # ---- index history subset
    ih = pd.read_parquet(data / "nse" / "index_history.parquet")
    from scanner.daily import FACTOR_INDICES, SECTOR_INDICES
    want = [c for c in FACTOR_INDICES + SECTOR_INDICES + ["India VIX"] if c in ih.columns]
    ih[want].iloc[-300:].to_parquet(nse / "index_history.parquet")
    print(f"fixtures written to {OUT} ({len(keep)} symbols x {DAYS} days)")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
