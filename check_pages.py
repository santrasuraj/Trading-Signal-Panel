"""Open every page's data on THIS copy and report any that fails - the same calls the dashboard makes, on this copy's own
data (a stock with no 200-day average yet, a fresh listing with results stored, an empty file all differ per copy).

    python check_pages.py                    every GET endpoint, stock pages for RELIANCE / NIFTY and the newest listings
    python check_pages.py TCS INFY           ... and these stocks too

Runs the app in this process (no server needed; nothing is started, sent or changed - only GET requests). A page's own
message ("no order flow today", "log in to FYERS", "not found") is fine; a crash or an internal error is not. Prints each
failing endpoint with the file and line it failed at, and ends with ALL OK or the number of failures (exit code 1).
"""
from __future__ import annotations

import re
import sys
import time
import traceback
import warnings

warnings.filterwarnings("ignore")

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from web.api.main import create_app  # noqa: E402

SKIP = {"job_id", "trade_id", "rest", "path"}       # ids of jobs / trades made on the fly; the page fallbacks
STREAMS = ("/api/stream/",)                         # live streams never end
SLOW_S = 20.0


def newest_listings(n: int = 3) -> list[str]:
    """The scan-universe stocks with the shortest history (no 200-day average yet): where missing values show up."""
    try:
        from web.api.services import data
        sc = data.screener()
        if sc is None or sc.empty:
            return []
        new = sc[sc["above_sma200"].isna()] if "above_sma200" in sc else sc.iloc[0:0]
        return [str(s) for s in new["symbol"].head(n)]
    except Exception:
        return []


def strategy_keys(client: TestClient) -> list[str]:
    try:
        j = client.get("/api/strategies").json()
        items = j if isinstance(j, list) else (j.get("strategies") or j.get("rows") or j.get("items") or [])
        return [x["key"] for x in items if isinstance(x, dict) and x.get("key")][:3]
    except Exception:
        return []


def main() -> int:
    t_all = time.time()
    app = create_app(warm=False)
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=True)
    syms = list(dict.fromkeys(["RELIANCE", "NIFTY", *newest_listings(), *[s.upper() for s in sys.argv[1:]]]))
    keys = strategy_keys(client) or ["momentum"]
    print(f"Checking every page's data: stocks {', '.join(syms)}; strategies {', '.join(keys)}")
    fails, slow, n = [], [], 0
    for r in [r for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods]:
        ps = re.findall(r"\{(\w+)(?::\w+)?\}", r.path)
        if set(ps) & SKIP or r.path.startswith(STREAMS):
            continue
        combos = [{}]
        if "symbol" in ps:
            combos = [{"symbol": s} for s in syms]
        if "key" in ps:
            combos = [{**c, "key": k} for c in combos for k in keys]
        for c in combos:
            url = r.path
            for k, v in c.items():
                url = re.sub(r"\{" + k + r"(?::\w+)?\}", v, url)
            t0 = time.time()
            n += 1
            try:
                resp = client.get(url)
                if resp.status_code == 500:            # 501 "not available yet", 404, 409 "log in" are the page's own
                    fails.append((url, f"HTTP 500: {resp.text[:200]}"))   # messages; 500 is a failure
            except Exception as e:
                tb = [f for f in traceback.extract_tb(e.__traceback__) if "site-packages" not in f.filename]
                where = f"{tb[-1].filename.split('stock_scanner')[-1].lstrip(chr(92) + '/')}:{tb[-1].lineno}" if tb else "?"
                fails.append((url, f"{type(e).__name__}: {e}  ({where})"))
            dt = time.time() - t0
            if dt > SLOW_S:
                slow.append(f"{url} {dt:.0f}s")
            print(f"\r  {n} checked", end="", flush=True)
    print()
    for url, why in fails:
        print(f"  FAIL  {url}\n        {why}")
    if slow:
        print(f"  slow (over {SLOW_S:.0f}s, usually NSE / Yahoo being slow): {', '.join(slow)}")
    print(f"\n{'ALL OK' if not fails else f'{len(fails)} page(s) failing'} - {n} checked in {time.time() - t_all:.0f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
