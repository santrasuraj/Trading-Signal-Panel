"""Run a scan from the command line (also used by the scheduled tasks and the dashboard).

  python run_scan.py               scan and print the summary
  python run_scan.py --telegram    also send the summary (or a failure alert) to Telegram
  python run_scan.py --no-update   use stored prices only (no download)
  python run_scan.py --status FILE write progress to FILE as JSON (used by the dashboard)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler

from scanner.alerts import format_daily, send_telegram
from scanner.daily import run_daily
from scanner.lock import ScanBusy
from scanner.settings import LOG_DIR, load_config


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
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lg = _logger()
    state = {"state": "running", "message": "Starting...", "progress": 0.0, "started": time.time()}

    def write_status(**kw):
        state.update(kw)
        if args.status:
            try:
                with open(args.status, "w", encoding="utf-8") as fh:
                    json.dump(state, fh)
            except OSError:
                pass

    def log(msg: str):
        print(msg, flush=True)
        lg.info(msg)
        write_status(message=msg)

    last = [0.0]

    def progress(done, total, sym):
        frac = done / max(total, 1)
        if frac - last[0] >= 0.02 or done == total:
            last[0] = frac
            write_status(progress=round(frac, 3), message=f"Downloading {sym} ({done}/{total})")

    write_status()
    cfg = load_config()
    try:
        result = run_daily(cfg, update=not args.no_update, progress=progress, log=log, by=args.by)
    except ScanBusy as e:
        log(str(e))
        write_status(state="busy")
        return 2
    except Exception as e:
        lg.error("Scan failed: %s\n%s", e, traceback.format_exc())
        print(f"\nScan FAILED: {e}", flush=True)
        write_status(state="failed", message=str(e))
        if args.telegram:
            send_telegram(f"⚠️ NSE Scanner: scan FAILED at {time.strftime('%H:%M')}\n{e}\n"
                          "Details: data/logs/scanner.log")
        return 1
    summary = format_daily(result, int((cfg.get("telegram") or {}).get("top_n", 10)))
    print("\n" + summary)
    if args.telegram:
        ok, msg = send_telegram(summary)
        log(f"Telegram: {msg}")
    write_status(state="done", progress=1.0, message=f"Done in {result['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
