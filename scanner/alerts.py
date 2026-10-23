"""Text summaries of a scan for the console and Telegram."""
from __future__ import annotations

from datetime import datetime

import requests

from .settings import env

ICON = {"working": "✅", "mixed": "🟡", "not-working": "❌", "unknown": "…"}
MOOD = {"good": "🟢", "bad": "🔴", "neutral": "🟡"}


def _pct(x, nd=1) -> str:
    return "-" if x is None else f"{x:+.{nd}f}%"


def paper_line(p: dict) -> str:
    """One line of live paper-trading results for a strategy (see paper.py)."""
    since = datetime.fromisoformat(p["start"]).strftime("%d %b")
    if not p.get("days"):
        return f"📒 Paper: started {since} - first fills at the next open"
    pnl = p.get("pnl")
    money = f" (₹{pnl:+,.0f})" if pnl is not None else ""
    return (f"📒 Paper since {since} ({p['days']} days): {_pct(p.get('return_pct'))}{money} | "
            f"Nifty 500 {_pct(p.get('n500_pct'))} | backtest expected {_pct(p.get('expected_pct'))}")


def format_daily(r: dict, top_n: int = 10) -> str:
    m = r["market"]
    when = datetime.fromisoformat(r["generated_at"]).strftime("%d %b %H:%M")
    price_note = (f"LIVE {r.get('live_source') or ''}".strip() if r.get("live") else "official NSE close")
    lines = [f"📈 NSE Scanner - {when} IST",
             f"Prices as of {r['data_date']} ({price_note})",
             f"{MOOD.get(m['level'], '')} Market {m['label']}: Nifty {m['nifty']:,.0f} ({_pct(m['nifty_change_pct'], 2)}), "
             f"VIX {m['vix']}, {m['breadth_50']:.0f}% of stocks above 50-DMA",
             m["advice"]]
    for s in r["strategies"]:
        if s["status"] == "not-working" and s["key"] == "legacy_rules":
            continue
        y1 = s["metrics"].get("12m") or {}
        full = s["metrics"]["full"]
        lines.append("")
        lines.append(f"{ICON.get(s['status'], '')} {s['name']}: {_pct(full.get('cagr_pct'))}/yr over "
                     f"{full['start'][:4]}-{full['end'][:4]}, last 12m {_pct(y1.get('return_pct'))} "
                     f"(Nifty {_pct((y1.get('benchmark') or {}).get('return_pct'))})")
        pp = (r.get("paper") or {}).get(s["key"])
        if pp:
            lines.append("  " + paper_line(pp))
        buys = [a for a in s["actions"] if a["action"] == "BUY"][:top_n]
        sells = [a for a in s["actions"] if a["action"] == "SELL"]
        if buys:
            lines.append("  BUY at next open: " + ", ".join(
                f"{a['symbol']} x{a['qty']} (~₹{a['price']:,.0f}{', stop ₹' + format(a['stop'], ',.0f') if a.get('stop') else ''}"
                f"{', ⚠ results ' + a['results_on'][5:] if a.get('results_warning') else ''})"
                for a in buys))
        if sells:
            lines.append("  SELL at next open: " + ", ".join(f"{a['symbol']} ({a['reason']})" for a in sells))
        if s["positions"]:
            lines.append("  Holding: " + ", ".join(f"{p['symbol']} {_pct(p['ret_pct'], 0)}" for p in s["positions"][:15]))
        if s.get("next_rebalance"):
            lines.append(f"  Next review: {s['next_rebalance']}")
    alerts = [h for h in r.get("holdings", []) if h.get("alerts")]
    if alerts:
        lines.append("")
        lines.append("💼 Your holdings:")
        for h in alerts:
            pnl = f" (P&L {_pct(h.get('pnl_pct'))})" if h.get("pnl_pct") is not None else ""
            lines.append(f"  {h['symbol']}{pnl}: " + "; ".join(h["alerts"]))
    if any(a.get("provisional") for s in r["strategies"] for a in s["actions"]):
        lines.append("")
        lines.append("⏱ Orders are provisional: the market is open and today's candle can still change.")
    lines.append("")
    lines.append("Rule-based signals tested on history - not investment advice. Decide yourself; always use a stop-loss.")
    return "\n".join(lines)


def send_telegram(text: str) -> tuple[bool, str]:
    token, chat_id = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Telegram not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)"
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):  # split on line boundaries, under Telegram's 4096 limit
        if len(cur) + len(line) > 3500:
            chunks.append(cur)
            cur = ""
        cur += line
    chunks.append(cur)
    try:
        for c in chunks:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat_id, "text": c, "disable_web_page_preview": True}, timeout=20)
            if not r.ok:
                return False, f"Telegram error {r.status_code}: {r.text[:200].replace(token, '***')}"
        return True, "sent"
    except requests.RequestException as e:
        return False, f"Telegram error: {type(e).__name__}"  # never print the URL: it contains the token
