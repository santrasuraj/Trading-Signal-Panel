"""Config view (read-only in P1), delivery cost preview and data health."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime

import pandas as pd

from scanner.costs import CostModel, TaxModel
from scanner.settings import IST, env

from . import alerts, data
from ..caches import file_key
from ..paths import P
from ..util import num


def _generated_epoch(lt: dict | None) -> float | None:
    try:
        return pd.Timestamp(lt["generated_at"]).timestamp() if lt else None
    except Exception:
        return None


def config_changed_since_scan(lt: dict | None) -> bool:
    gen = _generated_epoch(lt)
    key = file_key(P.config)
    return bool(gen is not None and key[1] is not None and key[1] / 1e9 > gen)


def config_view() -> dict:
    from scanner.strategies import build_strategies, strategy_lifecycle
    cfg = data.config()
    acct, flt, hd = cfg.get("account") or {}, cfg.get("filters") or {}, cfg.get("holdings_defaults") or {}
    costs = asdict(CostModel.from_config(cfg.get("costs")))
    tax = asdict(TaxModel.from_config(cfg.get("tax")))
    conf = cfg.get("strategies") or {}
    try:
        keys = [s.key for s in build_strategies(cfg, include_disabled=True)]
    except Exception:
        keys = []
    keys += [k for k in conf if k not in keys]
    strategies = {}
    for k in keys:
        c = conf.get(k) or {}
        strategies[k] = {"enabled": strategy_lifecycle(cfg, k)[0] == "active",
                         "params": {p: v for p, v in c.items() if p != "enabled"}}
    universe = str(cfg.get("universe") or "nifty500").lower()
    return {
        "account": {"capital": num(acct.get("capital")) or 500000.0, "min_position": num(acct.get("min_position")) or 0.0},
        "data_source": "yahoo" if str(cfg.get("data_source", "auto")).lower() == "yahoo" else "auto",
        "fyers_plan": "prime" if str(cfg.get("fyers_plan", "standard")).lower() == "prime" else "standard",
        "universe": universe if universe in ("nifty50", "nifty100", "nifty200", "nifty500") else "nifty500",
        "lookback_days": int(num(cfg.get("lookback_days")) or 3000),
        "filters": {"min_price": num(flt.get("min_price")) or 50.0, "min_turnover_cr": num(flt.get("min_turnover_cr")) or 5.0},
        "holdings_defaults": {"stop_loss_pct": num(hd.get("stop_loss_pct")) or 8.0,
                              "target_pct": num(hd.get("target_pct")) or 20.0},
        "results": {"warn_days": int(num((cfg.get("results") or {}).get("warn_days")) or 7)},
        "movers_count": int(num(cfg.get("movers_count")) or 15),
        "etfs": data.etfs(), "costs": costs, "tax": tax,
        "allocations": {str(k): float(v) for k, v in (cfg.get("allocations") or {}).items() if num(v) is not None},
        "strategies": strategies,
        "telegram": {"top_n": int(num((cfg.get("telegram") or {}).get("top_n")) or 10),
                     "configured": bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"))},
    }


def config_response() -> dict:
    key = file_key(P.config)
    mtime = datetime.fromtimestamp(key[1] / 1e9, IST).isoformat(timespec="seconds") if key[1] else None
    return {"values": config_view(), "file_mtime": mtime or "", "needs_rescan": config_changed_since_scan(data.latest())}


def _breakdown(cm: CostModel, value: float, side: str) -> dict:
    brokerage = min(value * cm.brokerage_pct / 100, cm.brokerage_max)
    exchange = value * cm.exchange_pct / 100
    sebi = value * cm.sebi_pct / 100
    gst = (brokerage + exchange + sebi) * cm.gst_pct / 100
    stt = value * cm.stt_pct / 100
    stamp = value * cm.stamp_buy_pct / 100 if side == "buy" else 0.0
    dp = cm.dp_per_sell if side == "sell" else 0.0
    slippage = value * cm.slippage_pct / 100
    total = brokerage + exchange + sebi + gst + stt + stamp + dp + slippage
    r = lambda x: round(x, 2)  # noqa: E731
    return {"value": r(value), "side": side, "brokerage": r(brokerage), "stt": r(stt), "exchange": r(exchange),
            "sebi": r(sebi), "stamp": r(stamp), "gst": r(gst), "dp": r(dp), "slippage": r(slippage),
            "total": r(total), "total_pct": round(total / value * 100, 4)}


def cost_preview(value: float) -> dict:
    cm = CostModel.from_config(data.config().get("costs"))
    buy, sell = _breakdown(cm, value, "buy"), _breakdown(cm, value, "sell")
    return {"value": value, "buy": buy, "sell": sell, "round_trip_pct": round(cm.round_trip_pct(value), 4)}


def _log_tail(lines: int) -> list[str]:
    try:
        with open(P.scan_log, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 400_000))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out = text.splitlines()[-lines:]
    return [scrub(x) for x in out]


_SECRET_RE = re.compile(r"(access_token|auth_code|secret_key|secret|token)=([^&\s\"']+)", re.I)


def scrub(line: str) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", line)


def scan_log(lines: int, level: str) -> dict:
    out = _log_tail(5000 if level == "error" else lines)
    if level == "error":
        out = [x for x in out if " ERROR " in x or "Traceback" in x or "FAILED" in x][-lines:]
    return {"path": str(P.scan_log), "lines": out}


def data_health() -> dict:
    lt = data.latest() or {}
    meta = data.store_meta()
    frames = data.store()
    close = frames["close"]
    store = {"version": data.store_version(),
             "first_date": close.index[0].date().isoformat() if len(close) else "",
             "last_date": close.index[-1].date().isoformat() if len(close) else "",
             "symbols": int(close.shape[1]), "trading_days": int(close.shape[0]), "fields": sorted(frames),
             "size_mb": data.store_size_mb()}
    failed = {}
    for s, v in (meta.get("failed") or {}).items():
        if isinstance(v, dict):
            failed[s] = {"count": int(v.get("count") or 0), "last_try": str(v.get("last_try") or "")}
    cas = [c for c in meta.get("corporate_actions") or [] if isinstance(c, dict)]
    recent = sorted(cas, key=lambda c: str(c.get("date", "")), reverse=True)[:20]
    ih = data.index_history()
    _, cached_on = data.results_events()
    log_size = P.scan_log.stat().st_size / 1024 if P.scan_log.exists() else 0.0
    errs = [x for x in _log_tail(3000) if " ERROR " in x]
    scans = alerts.scan_files()
    producers = {bool(h.get("has_producer")) for h in scans}
    ji = data.journal_info()
    uni = data.universe()
    pit_built = (P.pit / "CURRENT").exists()
    return {
        "store": store, "nse": {"status": lt.get("nse_status"), "complete_upto": lt.get("complete_upto")},
        "failed_symbols": failed, "stale_symbols": list(lt.get("stale_symbols") or []),
        "errors": {str(k): str(v) for k, v in (lt.get("errors") or {}).items()},
        "corporate_actions_recent": [{"symbol": str(c.get("symbol")), "date": str(c.get("date")),
                                      "factor": num(c.get("factor")) or 0.0, "reason": str(c.get("reason") or "")}
                                     for c in recent],
        "corporate_actions_total": len(cas),
        "index_history": ({"last_date": ih.index[-1].date().isoformat() if len(ih) else None, "columns": int(ih.shape[1])}
                          if ih is not None else None),
        "results_calendar": {"note": lt.get("results_note"), "cached_on": cached_on},
        "universe": {"name": data.universe_name(), "note": str(lt.get("universe") or ""), "size": int(len(uni))},
        "pit": {"built": pit_built,
                "note": ("A point-in-time universe has been built, but backtests still use today's index list "
                         "(survivorship bias) until it drives the scan." if pit_built else
                         "No point-in-time universe yet: backtests use today's index list (survivorship bias).")},
        "journal": {"exists": P.journal.exists(), "days": ji["days"] if ji else None,
                    "size_kb": round(P.journal.stat().st_size / 1024, 1) if P.journal.exists() else None},
        "logs": {"path": str(P.scan_log), "size_kb": round(log_size, 1), "last_error": errs[-1] if errs else None},
        "scans": {"count": len(scans), "newest": scans[0]["generated_at"] if scans else None,
                  "oldest": scans[-1]["generated_at"] if scans else None, "mixed_producers": len(producers) > 1},
    }
