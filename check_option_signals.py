"""Check the Options tab (Signals > Options) on THIS copy, independently of the code that makes it.

    python check_option_signals.py

  update    this copy has the options-signals rules (commit 624f5a7), the dashboard (web/ui/dist) is built with them and
            the running server (python -m web.serve, port 8600) serves them
  rules     every day's intraday options re-decided here with plain loops: none from a strategy that lost money in its
            backtest (config.yaml option_signals.evidence), one per strategy / stock / direction a day, never two at
            once on a stock
  page      the tab (the API the page reads) shows exactly the trades those rules keep, none cancelled, and its records
            (per source and per strategy) add up from them
  trades    every trade kept: CE for LONG / PE for SHORT, the stock's NSE lot, capital, max loss, P&L, return, open P&L
            and a stop exit at or below the stop
  pricing   trades opened since this copy was updated: no intraday one after 14:30; a stop below the entry and a
            target above it, on NSE's 5-paise tick, each equal to the option's modelled change (Black-76 here, with
            the trade's own IV, time decay of the hold included) added to the price paid; the delta near the 0.55 asked
            for; each closed trade's breakdown (stock move, decay, volatility, spread, charges) adding up to its P&L
  signal    the underlying's stop and target were still on the right sides of its price when the option was bought
  settled   no intraday option still open from an earlier day (the nightly settlement ran)

Prints OK / MISMATCH / NOTE per check and ends with ALL OK, or the number of problems (exit code 1).
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import urllib.request
import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

from scanner.settings import DATA_DIR, ROOT  # noqa: E402
from web.api.paths import configure  # noqa: E402

configure(ROOT, DATA_DIR)

from scanner import option_signals as osg  # noqa: E402
from scanner import option_verdict as ov  # noqa: E402

FIX = "624f5a7"
URL = "http://127.0.0.1:8600/api/options/signals"
IST = timezone(timedelta(hours=5, minutes=30))
R = 0.065                     # the risk-free rate the app prices with
HOLD = {"intraday": 0.1, "stock": 10.0}
NEAR = {"intraday": 0.55, "stock": 0.70}
problems: list[str] = []


def report(name: str, ok: bool | None, detail: str = "") -> None:
    tag = "NOTE    " if ok is None else "OK      " if ok else "MISMATCH"
    print(f"  {tag} {name}{(': ' + detail) if detail else ''}")
    if ok is False:
        problems.append(name)


def near(a, b, tol) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


# ------------------------------------------------------------------ plain arithmetic (independent of the app)
def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76(F: float, K: float, T: float, sigma: float, call: bool) -> float:
    if T <= 0 or sigma <= 0:
        return max(F - K, 0.0) if call else max(K - F, 0.0)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    df = math.exp(-R * T)
    return df * (F * ncdf(d1) - K * ncdf(d2)) if call else df * (K * ncdf(-d2) - F * ncdf(-d1))


def delta76(F: float, K: float, T: float, sigma: float, call: bool) -> float:
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return math.exp(-R * T) * (ncdf(d1) if call else ncdf(d1) - 1.0)


def years_left(expiry: str, at: str) -> float:
    close = datetime.combine(date.fromisoformat(expiry), datetime.min.time(), IST).replace(hour=15, minute=30)
    return max((close - datetime.fromisoformat(at)).total_seconds() / (365 * 86400), 15 / (365 * 24 * 60))


def decide(rows: list[dict], allowed: set | None) -> dict[str, str | None]:
    """Each intraday option's fate by the rules, replayed in the order they were opened: id -> None (kept) or the reason
    it is not taken."""
    fate: dict[str, str | None] = {}
    by_day = defaultdict(list)
    for r in rows:
        if r.get("source") == "intraday":
            by_day[r.get("day")].append(r)
    for day_rows in by_day.values():
        kept, open_until = set(), {}                # open_until: symbol -> closed_at of its kept option ("" = still open)
        for r in sorted(day_rows, key=lambda x: x.get("opened_at") or ""):
            st = (r.get("strategy") or {}).get("status") or "untested"
            key = ((r.get("strategy") or {}).get("key"), r["symbol"], r.get("direction"))
            sym = r["symbol"]
            busy = sym in open_until and (open_until[sym] == "" or open_until[sym] > (r.get("opened_at") or ""))
            if allowed is not None and st not in allowed:
                fate[r["id"]] = "lost" if st == "not-working" else "evidence"
            elif key in kept:
                fate[r["id"]] = "repeat"
            elif busy:
                fate[r["id"]] = "stacked"
            else:
                fate[r["id"]] = None
                kept.add(key)
                open_until[sym] = r.get("closed_at") or ""
    return fate


# ------------------------------------------------------------------ the checks
def check_update() -> dict | None:
    print("update")
    try:
        ok = subprocess.run(["git", "merge-base", "--is-ancestor", FIX, "HEAD"], cwd=ROOT,
                            capture_output=True).returncode == 0
        report("code", ok, "has the options-signals rules" if ok else "run git pull")
    except OSError:
        report("code", hasattr(osg, "tidy"), "git not found; checked the module instead")
    js = list((ROOT / "web" / "ui" / "dist" / "assets").glob("*.js"))
    built = any("Not taken" in p.read_text(encoding="utf-8", errors="ignore") for p in js)
    report("dashboard build", built, "includes the new Options card" if built else
           "rebuild it: cd web\\ui, npm install, npm run build")
    try:
        with urllib.request.urlopen(URL, timeout=20) as f:
            page = json.loads(f.read().decode("utf-8"))
    except Exception as e:
        report("server", None, f"not reachable on port 8600 ({type(e).__name__}); start python -m web.serve and "
                               f"run this again to check what the page shows")
        return None
    fresh = "evidence" in page and "skipped" in page
    report("server", fresh, "serves the new rules" if fresh else "still the old code: restart python -m web.serve")
    return page if fresh else None


def check_rules(rows: list[dict], fate: dict, rule: str) -> None:
    print(f"rules  (config.yaml option_signals.evidence: {rule})")
    days = sorted({r["day"] for r in rows if r.get("source") == "intraday"})
    for d in days[-5:]:
        mine = [r for r in rows if r.get("source") == "intraday" and r["day"] == d]
        why = defaultdict(int)
        for r in mine:
            why[fate[r["id"]] or "kept"] += 1
        report(d, None, f"{len(mine)} intraday options opened: " + ", ".join(f"{v} {k}" for k, v in sorted(why.items())))
    wrong = [f"{r['day']} {r['symbol']}" for r in rows if r.get("state") == "cancelled" and fate.get(r["id"]) is None]
    report("nothing cancelled that the rules keep", not wrong, ", ".join(wrong[:4]))
    waiting = sum(1 for r in rows if r.get("source") == "intraday" and fate.get(r["id"]) and r.get("state") != "cancelled")
    if waiting:
        report("journal", None, f"{waiting} not-taken trades are still marked open/closed in the file: the page hides "
                                f"them now and the live loop or the nightly settlement marks them cancelled")
    skips = osg.load_skips().get(days[-1] if days else "", {})
    if skips:
        report(f"not taken on {days[-1]} (never opened)", None,
               ", ".join(f"{len(v)} {k}" for k, v in sorted(skips.items())))


def check_page(page: dict, rows: list[dict], fate: dict, today: str, label: str) -> None:
    print(label)
    sig = page.get("signals") or []
    report("no cancelled trade shown", all(s.get("state") != "cancelled" for s in sig))
    wrong = [f"{s['symbol']} {(s.get('strategy') or {}).get('key')} ({fate[s['id']]})" for s in sig
             if s.get("source") == "intraday" and fate.get(s["id"]) is not None]
    report("no repeat, stacked or lost-strategy trade shown", not wrong, ", ".join(wrong[:4]))
    keep = [r for r in rows if r.get("state") != "cancelled" and fate.get(r["id"]) is None]
    show = [r for r in keep if r.get("state") == "open" or r.get("day") == today]
    if not show:                                   # weekend / before the first trade: the last session's
        last = max((r["day"] for r in keep), default=None)
        show = [r for r in keep if r["day"] == last]
    want = {r["id"] for r in show if r["source"] == "intraday"}
    got = {s["id"] for s in sig if s.get("source") == "intraday"}
    day = page.get("skipped_day")
    report(f"every kept intraday trade of {day} shown", want == got,
           f"{len(want)} expected, {len(got)} shown" + (f", missing {sorted(want - got)[:3]}" if want - got else ""))
    live = [r for r in rows if not (r.get("source") == "intraday" and fate.get(r["id"]) is not None)
            and r.get("state") != "cancelled"]
    for rec in page.get("record") or []:
        src = rec["source"]
        done = [r for r in live if r["source"] == src and r.get("state") == "closed" and r.get("pnl") is not None]
        pnl = round(sum(r["pnl"] for r in done), 2)
        opn = sum(1 for r in live if r["source"] == src and r.get("state") == "open")
        ok = rec["trades"] == len(done) and near(rec["pnl"], pnl, 0.05) and rec["open"] == opn
        report(f"record: {src}", ok, f"{len(done)} closed, P&L {pnl:,.2f}, {opn} open"
               + ("" if ok else f" (page: {rec['trades']}, {rec['pnl']}, {rec['open']})"))
        per = defaultdict(lambda: [0, 0, 0.0, 0])
        for r in live:
            if r["source"] != src:
                continue
            e = per[(r.get("strategy") or {}).get("key") or "?"]
            if r.get("state") == "open":
                e[3] += 1
            elif r.get("state") == "closed" and r.get("pnl") is not None:
                e[0] += 1
                e[1] += r["pnl"] > 0
                e[2] += r["pnl"]
        bad = [b["key"] for b in rec.get("by_strategy") or [] if b["key"] not in per or
               (b["trades"], b["wins"], b["open"]) != tuple(per[b["key"]][i] for i in (0, 1, 3)) or
               not near(b["pnl"], per[b["key"]][2], 0.05)]
        missing = set(per) - {b["key"] for b in rec.get("by_strategy") or []}
        if per:
            report(f"record: {src} by strategy", not bad and not missing, ", ".join(bad + sorted(missing)))


def check_trades(rows: list[dict], fate: dict, today: str) -> None:
    print("trades")
    lots = ov.lot_sizes()
    keep = [r for r in rows if r.get("state") != "cancelled" and fate.get(r["id"]) is None]
    recent = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    bad: dict[str, list[str]] = defaultdict(list)
    for r in keep:
        tag = f"{r['day']} {r['symbol']} {r.get('structure')}"
        lot, entry = r["lot"], r["entry"]
        debit = r.get("kind") == "debit"
        if r["source"] in ("intraday", "stock"):
            leg = r["legs"][0]
            if len(r["legs"]) != 1 or leg["type"] != ("CE" if r.get("direction") == "LONG" else "PE"):
                bad["CE for LONG, PE for SHORT"].append(tag)
            if r["day"] >= recent and lots and lots.get(r["symbol"]) not in (None, lot):
                bad["NSE lot"].append(f"{tag} ({lot} vs {lots.get(r['symbol'])})")
            if not near(r["capital"], entry * lot + (r.get("charges_in") or 0), 0.02):
                bad["capital = premium x lot + charges"].append(tag)
            stop, ch_in = r.get("stop"), r.get("charges_in") or 0
            loss = ((entry - stop) * lot + ch_in + osg._charges(stop * lot, "sell", date.fromisoformat(r["day"]))
                    if stop else entry * lot + ch_in)
            if not near(r["max_loss"], loss, 0.005 * lot + 0.05):     # the stop is stored to the paisa
                bad["max loss"].append(f"{tag} ({r['max_loss']} vs {loss:.2f})")
        if r.get("state") == "closed" and r.get("pnl") is not None:
            gross = ((r["exit"] - entry) if debit else (entry - r["exit"])) * lot
            if not near(r["pnl"], gross - (r.get("charges") or 0), 0.05):
                bad["P&L = (exit - entry) x lot - charges"].append(f"{tag} ({r['pnl']} vs {gross - r['charges']:.2f})")
            if not near(r.get("ret_pct"), r["pnl"] / (r["capital"] or 1) * 100, 0.06):
                bad["return = P&L / capital"].append(tag)
            if r.get("exit_reason") == "stop" and r.get("stop") is not None and \
                    (r["exit"] > r["stop"] + 1e-6 if debit else r["exit"] < r["stop"] - 1e-6):
                bad["a stop exit at or past the stop"].append(f"{tag} (exit {r['exit']}, stop {r['stop']})")
        if r.get("parts") and r.get("pnl") is not None and not near(sum(r["parts"].values()), r["pnl"], 0.1):
            bad["P&L breakdown adds up"].append(f"{tag} ({sum(r['parts'].values()):.2f} vs {r['pnl']})")
        if r.get("state") == "open" and r.get("unrealized") is not None and r.get("mark") is not None:
            if not near(r["unrealized"], ((r["mark"] - entry) if debit else (entry - r["mark"])) * lot, 0.05):
                bad["open P&L = (mark - entry) x lot"].append(tag)
    for name in ("CE for LONG, PE for SHORT", "NSE lot", "capital = premium x lot + charges", "max loss",
                 "P&L = (exit - entry) x lot - charges", "return = P&L / capital", "a stop exit at or past the stop",
                 "open P&L = (mark - entry) x lot", "P&L breakdown adds up"):
        report(name, not bad[name], f"{len(bad[name])} wrong, e.g. {bad[name][:2]}" if bad[name] else "")
    print(f"           ({len(keep)} trades checked)")


def check_pricing(rows: list[dict], fate: dict, since: str) -> None:
    print(f"pricing  (trades opened since this copy was updated, {since[:16].replace('T', ' ')})")
    new = [r for r in rows if r["source"] in ("intraday", "stock") and fate.get(r["id"]) is None
           and r.get("state") != "cancelled" and (r.get("opened_at") or "") >= since]
    if not new:
        report("pricing", None, "no trade opened since the update yet: run this again after the next session's trades")
        return
    closing = [f"{r['day']} {r['symbol']} {r['opened_at'][11:16]}" for r in new
               if r["source"] == "intraday" and r["opened_at"][11:16] >= "14:30"]
    report("no new intraday option after 14:30", not closing, ", ".join(closing[:4]))
    bad: dict[str, list[str]] = defaultdict(list)
    for r in new:
        tag = f"{r['day']} {r['symbol']}"
        leg, u = r["legs"][0], r["underlying"]
        call, K, iv = leg["type"] == "CE", float(leg["strike"]), float(leg["iv"]) / 100
        T = years_left(r["expiry"], r["opened_at"])
        S = float(u["price"])
        F = S * math.exp(R * T)
        base = black76(F, K, T, iv, call)
        T_hold = max(T - HOLD[r["source"]] / 365, 15 / (365 * 24 * 60))
        tol = max(0.20, 0.04 * r["entry"])        # the IV is stored to 0.1 point; the app's forward comes from the chain
        for name, lvl, got in (("stop", u.get("stop"), r.get("stop")), ("target", u.get("target"), r.get("target"))):
            if lvl is None:
                continue
            want = r["entry"] + black76(F * float(lvl) / S, K, T_hold, iv, call) - base
            if name == "stop":
                want = max(want, 0.05)
            usable = want < r["entry"] if name == "stop" else want > r["entry"]
            if got is None:
                if usable:
                    bad[f"{name} priced"].append(f"{tag} (none, expected {want:.2f})")
                continue
            if not near(got, want, tol):
                bad[f"{name} priced"].append(f"{tag} ({got} vs {want:.2f})")
            if abs(got * 20 - round(got * 20)) > 1e-6:
                bad["on the 5-paise tick"].append(f"{tag} {name} {got}")
            if (name == "stop" and got >= r["entry"]) or (name == "target" and got <= r["entry"]):
                bad[f"{name} on the right side of the entry"].append(f"{tag} ({got} vs {r['entry']})")
        d = delta76(F, K, T, iv, call)
        if abs(abs(d) - NEAR[r["source"]]) > 0.25:
            bad["delta near the one asked for"].append(f"{tag} ({d:+.2f})")
    for name in ("stop priced", "target priced", "on the 5-paise tick", "stop on the right side of the entry",
                 "target on the right side of the entry", "delta near the one asked for"):
        report(name, not bad[name], f"{len(bad[name])} wrong, e.g. {bad[name][:3]}" if bad[name] else "")
    print(f"           ({len(new)} trades checked)")


def check_signal(rows: list[dict], fate: dict) -> None:
    print("signal")
    crossed = []
    for r in rows:
        if r["source"] != "intraday" or fate.get(r["id"]) is not None or r.get("state") == "cancelled":
            continue
        u, up = r["underlying"], r.get("direction") == "LONG"
        p, s, t = u.get("price"), u.get("stop"), u.get("target")
        if p is None:
            continue
        if (s is not None and (p <= s if up else p >= s)) or (t is not None and (p >= t if up else p <= t)):
            crossed.append(f"{r['day']} {r['symbol']} {r['direction']} at {p} (stop {s}, target {t})")
    report("stop and target still ahead when bought", not crossed,
           f"{len(crossed)} bought after the signal's stop or target had passed, e.g. {crossed[:2]}" if crossed else "")


def check_settled(rows: list[dict], fate: dict, today: str) -> None:
    print("settled")
    stale = [f"{r['day']} {r['symbol']}" for r in rows if r["source"] == "intraday" and r.get("state") == "open"
             and fate.get(r["id"]) is None and r["day"] < today]
    report("no intraday option left open from an earlier day", not stale,
           f"{len(stale)} still open, e.g. {stale[:3]}: run the nightly F&O download (it settles them)" if stale else "")
    late = [r for r in rows if r.get("exit_reason") == "square-off 15:00" and fate.get(r["id"]) is None
            and (r.get("closed_at") or "")[11:16] > "15:02"]
    if late:
        when = sorted({(r.get("closed_at") or "")[:16].replace("T", " ") for r in late})
        report("square-off on time", None, f"{len(late)} squared off after 15:02 ({', '.join(when[-3:])}): the server "
                                           f"was busy or the PC asleep at 15:00 - the exit price is from that later time")


def main() -> int:
    t0 = datetime.now()
    rows = osg.load()
    rule = osg.evidence_rule()
    fate = decide(rows, osg.EVIDENCE[rule])
    today = osg.ist_now().date().isoformat()
    since = datetime.fromtimestamp(Path(osg.__file__).stat().st_mtime, IST).isoformat(timespec="seconds")
    print(f"Options tab check on {ROOT} - {len(rows)} trades in {osg.FILE}")
    page = check_update()
    try:
        st = json.loads((osg.RESULTS_DIR / "intraday.json").read_text(encoding="utf-8"))
        tested = str(st.get("generated_at") or st.get("asof") or "?")[:10]
        print(f"         strategy backtest (intraday.json) from {tested}: a strategy added after it shows 'untested'")
    except (OSError, ValueError):
        print("         no intraday backtest yet (intraday.json): every strategy shows 'untested'")
    check_rules(rows, fate, rule)
    label = "page  (what the running server shows)"
    if page is None:
        from web.api.services import optsig_svc
        page = optsig_svc.view()
        label = "page  (the server is not running the new code: checked what it will show once restarted)"
    check_page(page, rows, fate, today, label)
    check_trades(rows, fate, today)
    check_pricing(rows, fate, since)
    check_signal(rows, fate)
    check_settled(rows, fate, today)
    print(f"\n{'ALL OK' if not problems else f'{len(problems)} problem(s): ' + ', '.join(problems)}"
          f"  ({(datetime.now() - t0).total_seconds():.1f}s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
