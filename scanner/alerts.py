"""Text summary of a scan, for the console and Telegram."""
from __future__ import annotations

from datetime import datetime

import requests

from .settings import env

MOOD_ICON = {"good": "🟢", "bad": "🔴", "neutral": "🟡"}


def _pct(x) -> str:
    return "-" if x is None else f"{x:+.2f}%"


def format_summary(result: dict, top_n: int = 10) -> str:
    m = result.get("market", {})
    when = datetime.fromisoformat(result["generated_at"]).strftime("%d %b %Y %H:%M")
    lines = [f"📈 NSE Scan - {when} IST ({result['source']})"]
    if result.get("live"):
        lines.append("⏱ Market is open: today's signals can still change before the close.")
    lines.append(
        f"Market: {m.get('label', '?')} {MOOD_ICON.get(m.get('level'), '')} | "
        f"Nifty {m.get('nifty', '-')} ({_pct(m.get('nifty_change_pct'))}) | VIX {m.get('vix', '-')} | "
        f"{m.get('breadth_50', '-')}% stocks above 50-DMA | Adv/Dec {m.get('advances', '-')}/{m.get('declines', '-')}"
    )
    lines.append(m.get("advice", ""))

    for title, key in (("🟢 BUY signals", "buy"), ("🔴 SELL signals", "sell")):
        items = result.get(key, [])
        lines.append("")
        lines.append(f"{title} ({len(items)})")
        for i, e in enumerate(items[:top_n], 1):
            wr = f" | backtest win {e['backtest_win_rate']:.0f}%" if e.get("backtest_win_rate") is not None else ""
            lines.append(f"{i}. {e['symbol']} ₹{e['close']} ({_pct(e['change_pct'])}) - {', '.join(e['signals'])}{wr}")
        if not items:
            lines.append("none")

    alerts = [h for h in result.get("holdings", []) if h.get("alerts")]
    if alerts:
        lines.append("")
        lines.append("💼 Your holdings")
        for h in alerts:
            pnl = f" (P&L {_pct(h.get('pnl_pct'))})" if h.get("pnl_pct") is not None else ""
            lines.append(f"{h['symbol']}{pnl}: " + "; ".join(h["alerts"]))

    lines.append("")
    lines.append("Rule-based signals, not investment advice. Check the chart and decide yourself.")
    return "\n".join(lines)


def send_telegram(text: str) -> tuple[bool, str]:
    token, chat_id = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Telegram not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)"
    try:
        for k in range(0, len(text), 4000):
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat_id, "text": text[k:k + 4000],
                                    "disable_web_page_preview": True}, timeout=20)
            if not r.ok:
                return False, f"Telegram error: {r.text[:200]}"
        return True, "sent"
    except Exception as e:
        return False, f"Telegram error: {e}"
