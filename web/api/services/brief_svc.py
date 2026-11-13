"""Morning brief (GET /api/brief, POST /api/brief/send; 08:45 on Telegram when switched on): the day ahead in a few
plain lines, built from what the dashboard already knows:

  * the market's last close (Nifty 50) and today's economic events, expiries and holidays (calendar_svc);
  * your holdings' and watchlists' results, ex-dates (with the buy-by day) and recent announcements;
  * today's tested BUY / SELL list from the last scan (action_svc) and holdings below their stop (risk_svc);
  * the FYERS login state.
Every part is optional: a source that fails is left out, never the whole brief.
"""
from __future__ import annotations

from datetime import timedelta

from . import data
from ..util import today_ist


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def build() -> dict:
    from . import action_svc, calendar_svc, risk_svc
    today = today_ist()
    lines: list[str] = [f"Morning brief, {today.strftime('%a %d %b %Y')}"]
    sections: dict[str, list[str]] = {}

    c = _safe(lambda: data.store_close())
    if c is not None and "NIFTY50" in c.columns:
        n = c["NIFTY50"].dropna()
        if len(n) > 1:
            sections["Market"] = [f"Nifty 50 closed at {n.iloc[-1]:,.0f} ({(n.iloc[-1] / n.iloc[-2] - 1) * 100:+.2f}%) on "
                                  f"{n.index[-1].strftime('%d %b')}."]
    cal = _safe(lambda: calendar_svc.calendar(2, today=today), {}) or {}
    ev = cal.get("events") or []
    tod = [e for e in ev if e["date"] == today.isoformat()]
    tmr = [e for e in ev if e["date"] == (today + timedelta(days=1)).isoformat()]
    day: list[str] = []
    for e in tod:
        if e["kind"] == "holiday":
            day.append(f"NSE is closed today: {e['detail']}.")
        elif e["kind"] == "econ":
            day.append(f"{e.get('time') or ''} {e['detail'].split(' · ')[0]}".strip())
        elif e["kind"] == "expiry":
            day.append(f"F&O expiry today: {e['detail']}.")
    for e in tmr:
        if e["kind"] in ("econ", "holiday", "expiry"):
            day.append(f"Tomorrow: {e['detail'].split(' · ')[0]}")
    if day:
        sections["Today"] = day
    mine = [e for e in tod + tmr if e.get("mine") or e.get("watch")]
    yours: list[str] = []
    for e in mine:
        when = "today" if e["date"] == today.isoformat() else "tomorrow"
        who = f"{e['symbol']}{' (you hold)' if e.get('mine') else ''}"
        if e["kind"] == "results":
            yours.append(f"{who}: results {when} - a bigger move than usual is likely.")
        elif e["kind"] == "dividend":
            amt = f" Rs {e['amount']:g} a share" if e.get("amount") else ""
            yours.append(f"{who}: ex-dividend {when}{amt} (buy by {e.get('buy_by')}).")
        elif e["kind"] in ("rights", "bonus", "split", "buyback"):
            yours.append(f"{who}: {e['kind']} ex-date {when}.")
    ann = _safe(lambda: calendar_svc.announcements(None, 1, False, 5, today=today), {}) or {}
    for a in (ann.get("items") or [])[:3]:
        yours.append(f"{a['symbol']}: {a['subject']} (NSE filing)")
    if yours:
        sections["Your stocks"] = yours
    acts = _safe(lambda: action_svc.today(), {}) or {}
    cnt = acts.get("counts") or {}
    sig = []
    if cnt.get("buy") or cnt.get("sell"):
        names = [f"{c['state']} {c['symbol']}" for c in (acts.get("actions") or [])[:6]]
        sig.append(f"{cnt.get('buy', 0)} BUY, {cnt.get('sell', 0)} SELL from working strategies: {', '.join(names)}.")
    else:
        sig.append("No tested BUY or SELL today.")
    sections["Signals"] = sig
    risk = _safe(lambda: risk_svc.view(), {}) or {}
    hit = sorted({lt["symbol"] for lt in risk.get("lots") or [] if lt.get("stop_hit")})
    if hit:
        sections["Holdings"] = [f"Below your stop at the last close: {', '.join(hit)}."]
    try:
        from scanner.reminders import logged_in_today
        if not logged_in_today():
            sections["Login"] = ["Log in to FYERS before 09:14 for live prices, setups and order updates."]
    except Exception:
        pass
    for title, rows in sections.items():
        lines.append("")
        lines.append(title)
        lines += [f"- {r}" for r in rows]
    return {"date": today.isoformat(), "sections": sections, "text": "\n".join(lines)}


def send() -> dict:
    from scanner.alerts import send_telegram
    b = build()
    ok, detail = send_telegram(b["text"])
    return {**b, "sent": bool(ok), "detail": detail}
