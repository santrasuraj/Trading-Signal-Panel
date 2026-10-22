"""Run a scan from the command line (also used by the scheduled tasks).

  python run_scan.py                 scan and print summary
  python run_scan.py --telegram      also send the summary to Telegram
  python run_scan.py --backtest      also re-run the 2-year backtest
  python run_scan.py --source yahoo  force Yahoo data
"""
from __future__ import annotations

import argparse
import sys

from scanner.alerts import format_summary, send_telegram
from scanner.backtest import run_backtest
from scanner.scan import run_scan
from scanner.settings import load_config


def main() -> int:
    ap = argparse.ArgumentParser(description="NSE stock scanner")
    ap.add_argument("--telegram", action="store_true", help="send summary to Telegram")
    ap.add_argument("--backtest", action="store_true", help="re-run the backtest after scanning")
    ap.add_argument("--no-update", action="store_true", help="use cached prices only (no download)")
    ap.add_argument("--source", choices=["auto", "fyers", "yahoo"], help="override data_source in config.yaml")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    last_pct = [-1]

    def progress(done, total, sym):
        pct = int(done * 100 / total)
        if pct // 5 != last_pct[0] // 5:
            print(f"  {pct:3d}%  ({done}/{total})  {sym}", flush=True)
            last_pct[0] = pct

    result = run_scan(cfg, source=args.source, update=not args.no_update, progress=progress)

    if args.backtest:
        print("\nRunning backtest...")
        run_backtest(cfg, result["source_name"], progress=progress)
        # Re-scan so the results include the new win-rates (only a quick incremental download).
        result = run_scan(cfg, source=args.source, update=not args.no_update)

    summary = format_summary(result, int((cfg.get("telegram") or {}).get("top_n", 10)))
    print("\n" + summary)
    if result.get("errors"):
        print(f"\n({len(result['errors'])} symbols had download problems - see the dashboard for details)")

    if args.telegram:
        ok, msg = send_telegram(summary)
        print(f"\nTelegram: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
