"""Run a scan from the command line (also used by the scheduled tasks and the dashboard).

  python run_scan.py               scan and print the summary
  python run_scan.py --telegram    also send the summary (or a failure alert) to Telegram
  python run_scan.py --no-update   use stored prices only (no download)
  python run_scan.py --live-only   scan only while the market is open (today's live candle, provisional signals;
                                   used by the scheduled task every 30 minutes in market hours)
  python run_scan.py --status FILE write progress to FILE as JSON (used by the dashboards and scheduled tasks;
                                   only the scan holding the lock writes it)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

if sys.stderr is None:   # pythonw (the scheduled tasks) has no console: keep even an import error below in a file
    _console_log = Path(__file__).resolve().parent / "data" / "logs" / "scan_console.log"
    try:
        _console_log.parent.mkdir(parents=True, exist_ok=True)
        _big = _console_log.exists() and _console_log.stat().st_size > 1_000_000
        sys.stderr = open(_console_log, "w" if _big else "a", encoding="utf-8", buffering=1)
    except OSError:
        pass

from scanner.alerts import format_daily, send_telegram  # noqa: E402
from scanner.daily import run_daily  # noqa: E402
from scanner.lock import ScanBusy  # noqa: E402
from scanner.settings import LOG_DIR, load_config  # noqa: E402
from scanner.store import _replace  # noqa: E402


def _logger() -> logging.Logger:
    lg = logging.getLogger("scanner")
    if not lg.handlers:
        h = RotatingFileHandler(LOG_DIR / "scanner.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
    return lg


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE stock scanner")
    ap.add_argument("--telegram", action="store_true", help="send the summary to Telegram")
    ap.add_argument("--no-update", action="store_true", help="use stored prices only")
    ap.add_argument("--status", help="write progress JSON to this file")
    ap.add_argument("--by", default="manual", help="who started the scan (shown if another scan is blocked)")
    ap.add_argument("--live-only", action="store_true",
                    help="exit unless the market is open now (holidays, weekends, outside 09:15-15:30)")
    args = ap.parse_args()
    if args.live_only:
        from scanner.intraday.live import market_open_now
        if not market_open_now():
            print("Market is not open now: no live scan.", flush=True)
            return 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lg = _logger()
    state = {"state": "running", "message": "Starting...", "progress": 0.0, "started": time.time()}
    # The status file is shared by every scan (dashboards, scheduled tasks): only the process that holds the scan
    # lock writes it, so a scan that finds another one running never overwrites that scan's progress.
    owner = [False]

    def write_status(**kw):
        state.update(kw)
        if not (args.status and owner[0]):
            return
        tmp = f"{args.status}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            _replace(tmp, args.status)   # atomic: a dashboard polling the file never reads half of it
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # Progress 0..1: downloads take the first half of a full scan, testing the strategies the rest
    # (a re-check without download is all testing). daily.py logs "Testing strategy i/n: name".
    dl_share = 0.0 if args.no_update else 0.5
    testing = re.compile(r"^Testing strategy (\d+)/(\d+)")

    def log(msg: str):
        owner[0] = True   # run_daily only logs (and reports progress) while it holds the scan lock
        print(msg, flush=True)
        lg.info(msg)
        m = testing.match(msg)
        if m:
            i, n = int(m.group(1)), max(int(m.group(2)), 1)
            write_status(message=msg, progress=round(dl_share + (1 - dl_share) * (i - 1) / n, 3))
        else:
            write_status(message=msg)

    last = [0.0]

    def progress(done, total, sym):
        owner[0] = True
        frac = done / max(total, 1)
        if frac - last[0] >= 0.02 or done == total:
            last[0] = frac
            write_status(progress=round(frac * dl_share, 3), message=f"Downloading {sym} ({done}/{total})")

    cfg: dict = {}
    try:
        cfg = load_config()   # inside the try: a broken config.yaml must end as a logged, reported failure
        result = run_daily(cfg, update=not args.no_update, progress=progress, log=log, by=args.by)
    except ScanBusy as e:
        print(str(e), flush=True)
        lg.info(str(e))
        if args.status and not os.path.exists(args.status):   # a dashboard cleared it for this run: tell it
            owner[0] = True
            write_status(state="busy", message=str(e))
        if args.telegram:   # a skipped scheduled scan must not look like a quiet day
            send_telegram(f"⚠️ NSE Scanner: the scan at {time.strftime('%H:%M')} was skipped.\n{e}")
        return 2
    except Exception as e:
        owner[0] = True
        lg.error("Scan failed: %s\n%s", e, traceback.format_exc())
        print(f"\nScan FAILED: {e}", flush=True)
        write_status(state="failed", message=str(e))
        if args.telegram:
            send_telegram(f"⚠️ NSE Scanner: scan FAILED at {time.strftime('%H:%M')}\n{e}\n"
                          "Details: data/logs/scanner.log")
        return 1
    owner[0] = True
    # The scan itself is finished and saved: tell the dashboard now, before the slower smart-money download.
    write_status(state="done", progress=1.0, message=f"Done in {result['elapsed_s']}s")
    if not args.no_update:
        # Smart money (docs/smart_money_spec.md): NSE bulk/block deals, insider trades, FII/DII and shareholding.
        # Own lock and per-source error handling: it never fails the finished scan.
        try:
            from scanner import smart_money
            smart_money.refresh(days=365, log=lambda m: (print(m, flush=True), lg.info(m)))
        except Exception as e:
            lg.error("Smart money refresh failed: %s\n%s", e, traceback.format_exc())
            print(f"Smart money refresh failed (skipped): {e}", flush=True)
    try:
        summary = format_daily(result, int((cfg.get("telegram") or {}).get("top_n", 10)))
    except Exception as e:   # the scan finished and is saved: a summary problem must not leave it "running"
        lg.error("Summary failed: %s\n%s", e, traceback.format_exc())
        summary = (f"NSE Scanner: scan finished at {time.strftime('%H:%M')}, but the summary could not be "
                   f"written ({type(e).__name__}). Open the dashboard. Details: data/logs/scanner.log")
    try:
        from scanner import smart_money
        sm_lines = smart_money.summary_lines()   # [] when nothing is cached
    except Exception:
        sm_lines = []
    if sm_lines:
        summary += "\n\n" + "\n".join(sm_lines)
    print("\n" + summary)
    if args.telegram:
        ok, msg = send_telegram(summary)
        lg.info(f"Telegram: {msg}")
        print(f"Telegram: {msg}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
