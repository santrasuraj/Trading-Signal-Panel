"""NSE Scanner v2 dashboard.   Run:  streamlit run app.py   (or double-click 3_dashboard.bat)"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from scanner import paper
from scanner.costs import CostModel
from scanner.daily import CURVES_FILE, load_curves, load_latest
from scanner.holdings import load_holdings, save_holdings
from scanner.indicators import add_indicators
from scanner.lock import running_scan
from scanner.fyers_limits import FyersRateLimited
from scanner.providers import FyersAuthError, get_fyers, load_token
from scanner.settings import RESULTS_DIR, ROOT, ist_today, load_config
from scanner.store import PanelStore, load_store

STATUS_FILE = RESULTS_DIR / "status.json"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console popping up

st.set_page_config(page_title="NSE Scanner", page_icon="📈", layout="wide")

GREEN, RED, AMBER, GREY = "#1a9e55", "#d43c3c", "#d99a00", "#8a94a0"
STATUS = {"working": ("✅ Working now", GREEN), "mixed": ("🟡 Mixed", AMBER),
          "not-working": ("❌ Not working", RED), "unknown": ("… Not enough data", GREY)}
DISCLAIMER = ("Rule-based signals from historical testing - not investment advice. Past results do not guarantee "
              "future returns. Always use a stop-loss and decide yourself.")

cfg = load_config()


# ----------------------------------------------------------------------------- helpers
def fmt_time(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %Y, %I:%M %p")


def pct(x, signed=True, nd=1) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:+.{nd}f}%" if signed else f"{x:.{nd}f}%"


def rupees(x) -> str:
    return "-" if x is None else f"₹{x:,.0f}"


def color_signed(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return f"color: {GREEN}" if v > 0 else f"color: {RED}" if v < 0 else ""


def table(rows: list[dict], columns: dict[str, str], signed: tuple[str, ...] = (), fmt: dict | None = None,
          height: int | None = None, empty: str = "Nothing here right now."):
    if not rows:
        st.info(empty)
        return
    df = pd.DataFrame(rows)
    for k in columns:
        if k not in df.columns:
            df[k] = None
    df = df[list(columns)]
    styler = df.rename(columns=columns).style.format(
        {columns[k]: v for k, v in (fmt or {}).items() if k in columns}, na_rep="-")
    signed_cols = [columns[k] for k in signed if k in columns]
    if signed_cols:
        styler = styler.map(color_signed, subset=signed_cols)
    st.dataframe(styler, hide_index=True, **({"height": height} if height else {}))


@st.cache_data(show_spinner=False)
def cached_curves(mtime: float):
    return load_curves()


@st.cache_data(show_spinner=False)
def cached_store(version: str):
    return load_store()


@st.cache_data(show_spinner=False)
def cached_paper(version: str, journal_mtime: float, costs_json: str) -> dict:
    """paper.paper_report() for the current store, journal and charges (recomputed when any changes)."""
    return paper.paper_report(cached_store(version), CostModel.from_config(json.loads(costs_json)))["strategies"]


def file_mtime(p) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def read_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def start_background(script: str, *args: str) -> None:
    subprocess.Popen([sys.executable, str(ROOT / script), *args], cwd=str(ROOT), creationflags=NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_login_window() -> None:
    """Fyers login in its own console window (it may ask you to paste the address after logging in)."""
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", str(ROOT / "1_login.bat")], cwd=str(ROOT),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        start_background("login.py")


@st.fragment(run_every=2)
def scan_monitor():
    """Polls the background scan and reloads the page when it finishes."""
    if not st.session_state.get("scan_started"):
        return
    s = read_status()
    finished = s.get("state") in ("done", "failed", "busy")
    # Right after launching, the background process may not have taken the lock / written status yet.
    launching = time.time() - st.session_state.get("scan_launched_at", 0) < 30 and not finished
    if running_scan() or launching:
        st.progress(float(s.get("progress") or 0.0), text=s.get("message") or "Starting...")
        st.caption("You can keep using the dashboard; it refreshes when the scan finishes.")
        return
    st.session_state.scan_started = False
    if s.get("state") == "done":
        st.rerun(scope="app")
    elif s.get("state") in ("failed", "busy"):
        st.session_state.scan_error = s.get("message")
        st.rerun(scope="app")


# ----------------------------------------------------------------------------- sidebar
latest = load_latest()
with st.sidebar:
    st.title("📈 NSE Scanner")
    tok = load_token()
    if tok and tok.get("created", "")[:10] == ist_today().isoformat():
        st.success("Fyers logged in today - real-time prices")
    else:
        st.warning("Not logged in to Fyers today. Live prices come from Yahoo (~15 min delay).")
        if st.button("🔑 Log in to Fyers", help="Opens the Fyers login page in your browser (needed once a day)."):
            open_login_window()
            st.info("A login window and the Fyers page are opening. Follow the steps in the window, "
                    "then refresh this page.")
    busy = bool(running_scan()) or st.session_state.get("scan_started", False)
    if st.button("🔄 Run scan now", type="primary", disabled=busy):
        STATUS_FILE.unlink(missing_ok=True)
        start_background("run_scan.py", "--status", str(STATUS_FILE), "--by", "dashboard")
        st.session_state.scan_started = True
        st.session_state.scan_launched_at = time.time()
        st.session_state.scan_error = None
        st.rerun()
    if running_scan() and not st.session_state.get("scan_started"):
        st.session_state.scan_started = True   # a scheduled/manual scan is running: follow it too
    scan_monitor()
    if st.session_state.get("scan_error"):
        st.error(f"Scan problem: {st.session_state.scan_error}")
    if latest:
        st.divider()
        st.caption(f"**Last scan:** {fmt_time(latest['generated_at'])} ({latest['elapsed_s']}s)")
        st.caption(f"**Prices as of:** {latest['data_date']}"
                   + (f" - live, {latest['live_source']}" if latest.get("live") else " - official NSE close"))
        st.caption(f"**Universe:** {latest['universe']} · {latest['stocks']} liquid stocks")
        bt_mode = (latest.get("backtest") or {}).get("universe", "current")
        st.caption("**Backtests:** " + ("point-in-time top 500 (survivorship-free)" if bt_mode == "point_in_time"
                                        else "today's list (flattered by survivorship bias)"))
        st.caption(f"**Your capital:** {rupees(latest['capital'])} (change in config.yaml)")
    st.divider()
    st.caption(DISCLAIMER)

if not latest:
    st.header("Welcome 👋")
    st.write("Click **🔄 Run scan now** on the left. The first run downloads 8 years of prices for ~500 stocks "
             "and repairs them with NSE's official data (about 4 minutes). After that, scans take ~20 seconds.")
    st.stop()

# ----------------------------------------------------------------------------- header
m = latest["market"]
{"good": st.success, "bad": st.error}.get(m["level"], st.warning)(f"**Market: {m['label']}** - {m['advice']}")
if latest.get("live"):
    st.info("⏱ Market is open: today's candle is still forming. Signals marked *provisional* can change by 3:30 PM.")
c = st.columns(5)
c[0].metric("Nifty 50", f"{m['nifty'] or 0:,.0f}", pct(m["nifty_change_pct"], nd=2))
c[1].metric("India VIX", f"{m['vix'] or 0:.1f}", pct(m["vix_change_pct"], nd=2), delta_color="inverse")
c[2].metric("Stocks above 50-DMA", pct(m["breadth_50"], signed=False, nd=0))
c[3].metric("Up / Down today", f"{m['advances']}/{m['declines']}")
c[4].metric("Nifty trend", "Up ▲" if m["regime_up"] else "Down ▼",
            help="Up = Nifty above its 200-day average. Strategies only open new positions in an up trend.")

strats = latest["strategies"]
tabs = st.tabs(["🏆 Strategies", "✅ Today's actions", "📒 Paper trading", "💼 My holdings", "📊 Market", "📈 Chart",
                "ℹ️ Data & settings"])

# ----------------------------------------------------------------------------- strategies
with tabs[0]:
    st.caption("Every strategy is re-tested on ~8 years of real NSE data after each scan, buying at the next day's "
               "open and paying full Indian charges (STT, stamp duty, GST, DP, slippage). **Working now** = beat both "
               "Nifty and the average stock over the last 12 and 6 months.")
    rows = []
    for s in strats:
        full, y1, m6 = s["metrics"]["full"], s["metrics"].get("12m", {}), s["metrics"].get("6m", {})
        rows.append({
            "name": s["name"], "status": STATUS.get(s["status"], (s["status"],))[0],
            "cagr": full.get("cagr_pct"), "at": full.get("after_tax_cagr_pct"),
            "range": "{:.0f}-{:.0f}%".format(*full["cagr_range"]) if full.get("cagr_range") else "-",
            "dd": full.get("max_dd_pct"), "sharpe": full.get("sharpe"),
            "y1": y1.get("return_pct"), "y1n": (y1.get("benchmark") or {}).get("return_pct"),
            "m6": m6.get("return_pct"), "win": full.get("win_rate"), "trades": full.get("trades"),
        })
    table(rows, {"name": "Strategy", "status": "Status", "cagr": "Yearly return %", "range": "Timing range",
                 "at": "After tax %",
                 "dd": "Worst drop %",
                 "sharpe": "Sharpe", "y1": "Last 12m %", "y1n": "Nifty 12m %", "m6": "Last 6m %",
                 "win": "Win rate %", "trades": "Trades"},
          signed=("cagr", "at", "y1", "y1n", "m6", "dd"),
          fmt={"cagr": "{:+.1f}", "at": "{:+.1f}", "dd": "{:.1f}", "sharpe": "{:.2f}", "y1": "{:+.1f}", "y1n": "{:+.1f}",
               "m6": "{:+.1f}", "win": "{:.0f}", "trades": "{:.0f}"})
    full0 = strats[0]["metrics"]["full"]
    bench = full0.get("benchmark", {})
    ew = full0.get("ew_benchmark", {})
    n5 = full0.get("n500_benchmark", {})
    st.caption(f"Same period ({full0['start']} → {full0['end']}): Nifty 50 {pct(bench.get('cagr_pct'))}/yr "
               f"({pct(bench.get('after_tax_cagr_pct'))} after tax, worst drop {pct(bench.get('max_dd_pct'), signed=False)}); "
               f"**real Nifty 500 index {pct(n5.get('cagr_pct'))}/yr** (worst drop {pct(n5.get('max_dd_pct'), signed=False)}); "
               f"average stock in the test universe {pct(ew.get('cagr_pct'))}/yr. *Timing range* = the same rules rebalanced "
               "a few days earlier or started a few weeks later - expect anything in that range. "
               "*After tax* = short-term gains taxed at "
               "20.8% every April, long-term at 13% above ₹1.25 lakh (buy & hold pays once, at the end).")
    bt_info = latest.get("backtest") or {}
    if bt_info.get("universe") == "point_in_time":
        st.info(f"**Survivorship-free test.** {bt_info.get('note', '')} So the companies that later crashed, "
                "were merged away or delisted are included, and hindsight does not flatter these numbers. Today's "
                "orders still come from today's Nifty 500 list. Backtests still overstate real results a little (luck in the "
                "rebalance day, and the future is never the past): NSE's own momentum indices beat their parent "
                "index by about 3-6% a year over 20 years. **Expect an edge of a few % a year, not 40%.** Judge a "
                "strategy by how much it beats the **average stock** and the **Nifty 500** lines.")
    else:
        st.warning("**Reality check:** these tests use *today's* Nifty 500 list, so companies that collapsed or were "
                   f"dropped are missing - every number above is flattered. The gap between the average stock in this "
                   f"list ({pct(ew.get('cagr_pct'))}/yr) and the real Nifty 500 index ({pct(n5.get('cagr_pct'))}/yr) "
                   "shows how big that bias is (about 8% a year of it is pure survivorship, by our lab's estimate). "
                   "Set `backtest_universe: point_in_time` in config.yaml (and run 4_build_universe.bat once) for "
                   "survivorship-free tests. NSE's own momentum indices, which have no such bias, beat their parent "
                   "index by about 3-6% a year over 20 years. **Expect an edge of a few % a year, not 40%.** Judge "
                   "strategies by how much they beat the **average stock** line.")

    curves = cached_curves(file_mtime(CURVES_FILE))
    if curves is not None and not curves.empty:
        names = {s["key"]: s["name"] for s in strats}
        show = st.multiselect("Compare growth of ₹1", list(curves.columns),
                              default=[c for c in curves.columns if c in (strats[0]["key"], "NIFTY 500", "Average stock")],
                              format_func=lambda k: names.get(k, k))
        fig = go.Figure()
        for col in show:
            fig.add_trace(go.Scatter(x=curves.index, y=curves[col], name=names.get(col, col), mode="lines",
                                     line=dict(width=2.2 if col in names else 1.4,
                                               dash=None if col in names else "dot")))
        fig.update_layout(height=420, yaxis_type="log", yaxis_title="Growth of ₹1 (log scale)",
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.02, yanchor="bottom"))
        st.plotly_chart(fig)

    st.subheader("Year by year")
    years = sorted({y for s in strats for y in s["yearly"]})
    yt = pd.DataFrame({s["name"]: [s["yearly"].get(y) for y in years] for s in strats}, index=years).T
    st.dataframe(yt.style.format("{:+.0f}%", na_rep="-").map(color_signed))

    for s in strats:
        with st.expander(f"{STATUS.get(s['status'], ('',))[0]}  ·  {s['name']}"):
            st.write(s["description"])
            st.caption(s["status_reason"])
            f_ = s["metrics"]["full"]
            k = st.columns(6)
            k[0].metric("Yearly return", pct(f_.get("cagr_pct")))
            k[1].metric("Worst drop", pct(f_.get("max_dd_pct"), signed=False))
            k[2].metric("Win rate", pct(f_.get("win_rate"), signed=False, nd=0))
            k[3].metric("Avg win / loss", f"{pct(f_.get('avg_win_pct'))} / {pct(f_.get('avg_loss_pct'))}")
            k[4].metric("Profit factor", f"{f_.get('profit_factor') or 0:.2f}")
            k[5].metric("Time invested", pct(f_.get("exposure_pct"), signed=False, nd=0))
            st.caption("Most recent closed trades")
            table(s["recent_trades"], {"symbol": "Stock", "entry": "Bought", "exit": "Sold", "ret_pct": "Return %",
                                       "days": "Days", "reason": "Exit reason"},
                  signed=("ret_pct",), fmt={"ret_pct": "{:+.1f}"}, empty="No trades yet.")

# ----------------------------------------------------------------------------- today's actions
with tabs[1]:
    choice = st.selectbox("Strategy", [s["key"] for s in strats],
                          format_func=lambda k: next(f"{STATUS.get(s['status'], ('',))[0]} · {s['name']}"
                                                     for s in strats if s["key"] == k))
    s = next(x for x in strats if x["key"] == choice)
    if s["status"] == "not-working":
        st.error("This strategy has NOT been working recently. Shown for comparison only.")
    if not m["regime_up"]:
        st.warning("Nifty is below its 200-day average, so this strategy is not opening new positions. "
                   "This rule avoided much of the 2020 and 2022 falls in testing.")
    st.write(f"**Model portfolio:** up to {s['max_positions']} stocks, about {rupees(s['per_position'])} each "
             f"(your capital ÷ {s['max_positions']})."
             + (f" Next review: **{s['next_rebalance']}**." if s.get("next_rebalance") else ""))
    st.subheader("Orders for the next market open")
    for a in s["actions"]:
        if a.get("results_warning"):
            st.warning(f"**{a['symbol']}** reports quarterly results on {a['results_on']} "
                       f"(in {a['results_in_days']} days). Prices often jump or fall sharply on results - "
                       "consider waiting until after the announcement.")
    table(s["actions"], {"action": "Action", "symbol": "Stock", "company": "Company", "price": "Last price ₹",
                         "qty": "Qty", "amount": "Amount ₹", "stop": "Stop-loss ₹", "results_on": "Results on",
                         "reason": "Why"},
          fmt={"price": "₹{:,.2f}", "amount": "₹{:,.0f}", "stop": "₹{:,.2f}"},
          empty="No orders: nothing to buy or sell at the next open.")
    if any(a.get("provisional") for a in s["actions"]):
        st.caption("Provisional: based on today's still-forming candle. Re-check after 3:30 PM.")
    st.subheader("Current model holdings")
    table(s["positions"], {"symbol": "Stock", "company": "Company", "entry_date": "Bought", "entry_price": "Buy ₹",
                           "last_price": "Now ₹", "ret_pct": "Return %", "stop": "Stop ₹", "days": "Days held",
                           "results_on": "Results on"},
          signed=("ret_pct",), fmt={"entry_price": "₹{:,.2f}", "last_price": "₹{:,.2f}", "ret_pct": "{:+.1f}",
                                    "stop": "₹{:,.2f}"},
          empty="The model portfolio is in cash right now.")
    if s["ranking"]:
        st.subheader("Current ranking (strongest first)")
        table(s["ranking"], {"rank": "#", "symbol": "Stock", "company": "Company", "industry": "Sector",
                             "price": "Price ₹", "score": "Score", "ret_6m": "6m %", "ret_12m": "12m %",
                             "rs": "RS (1-99)", "results_on": "Results on", "in_portfolio": "Held"},
              signed=("ret_6m", "ret_12m"), fmt={"price": "₹{:,.2f}", "score": "{:.2f}", "ret_6m": "{:+.0f}",
                                                 "ret_12m": "{:+.0f}", "rs": "{:.0f}"}, height=520)

# ----------------------------------------------------------------------------- paper trading
with tabs[2]:
    st.caption("**Live proof instead of backtests.** Every scan of a completed day (after ~6 PM, or before 9:15 AM) "
               "writes each strategy's orders and model portfolio to a journal. A paper portfolio per strategy follows "
               "them: filled at the next day's official NSE open, with full charges and slippage, stop-losses applied, "
               "starting from your capital on the first journal day (on day one it buys the model's current holdings). "
               "Unlike the backtest, nothing here can be fitted to the past or flattered by survivorship. "
               "Intraday scans are provisional and never journaled.")
    reports = cached_paper(PanelStore().version(), file_mtime(paper.JOURNAL_FILE),
                           json.dumps(cfg.get("costs") or {}, sort_keys=True))
    if not reports:
        st.info("No paper trades yet. The journal starts automatically with the next scan of a completed trading day.")
    else:
        keys = [s_["key"] for s_ in strats]
        order = [k_ for k_ in keys if k_ in reports] + [k_ for k_ in reports if k_ not in keys]
        rows = []
        for k_ in order:
            sm = reports[k_]["summary"]
            rows.append({"name": sm["name"], "since": sm["start"], "days": sm["days"], "ret": sm["return_pct"],
                         "pnl": sm["pnl"], "n50": sm["nifty_pct"], "n500": sm["n500_pct"],
                         "exp": sm["expected_pct"], "trades": sm["trades"], "open": sm["open"]})
        table(rows, {"name": "Strategy", "since": "Since", "days": "Days", "ret": "Paper %", "pnl": "P&L ₹",
                     "n50": "Nifty 50 %", "n500": "Nifty 500 %", "exp": "Backtest expected %",
                     "trades": "Closed trades", "open": "Holding"},
              signed=("ret", "pnl", "n50", "n500", "exp"),
              fmt={"ret": "{:+.2f}", "pnl": "₹{:+,.0f}", "n50": "{:+.2f}", "n500": "{:+.2f}", "exp": "{:+.2f}",
                   "days": "{:.0f}", "trades": "{:.0f}", "open": "{:.0f}"})
        st.caption("*Backtest expected* = what the Nifty 500 actually did over the same days, plus the lead over it "
                   "that the backtest promised for that many days.")
        pk = st.selectbox("Show details for", order, format_func=lambda k_: reports[k_]["summary"]["name"])
        rep, sm = reports[pk], reports[pk]["summary"]
        k = st.columns(5)
        k[0].metric("Paper portfolio", rupees(sm["equity"]), pct(sm["return_pct"], nd=2))
        k[1].metric("Nifty 500, same days", pct(sm["n500_pct"], nd=2))
        k[2].metric("Backtest expected", pct(sm["expected_pct"], nd=2))
        k[3].metric("Worst drop", pct(sm["max_dd_pct"], signed=False))
        k[4].metric("Charges + slippage", rupees(sm["fees"] + sm["slippage"]))
        {"good": st.success, "bad": st.error}.get(sm["level"], st.info)(f"**{sm['verdict']}**")
        if sm.get("comparison"):
            st.write(sm["comparison"])
        if len(rep["equity"]) > 1:
            fig = go.Figure()
            for name_, pts in (("Paper portfolio", rep["equity"]), ("NIFTY 50", rep["nifty50"]),
                               ("NIFTY 500", rep["nifty500"])):
                if pts:
                    xs, ys = zip(*pts)
                    paper_line_ = name_ == "Paper portfolio"
                    fig.add_trace(go.Scatter(x=list(xs), y=list(ys), name=name_, mode="lines",
                                             line=dict(width=2.4 if paper_line_ else 1.4,
                                                       dash=None if paper_line_ else "dot")))
            fig.update_layout(height=380, yaxis_title=f"Value of {rupees(rep['capital'])}",
                              margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.02, yanchor="bottom"))
            st.plotly_chart(fig)
        if rep["pending"]:
            st.subheader("Paper orders for the next open")
            table(rep["pending"], {"action": "Action", "symbol": "Stock", "reason": "Why"})
        st.subheader("Paper holdings")
        table([{**o, "stop": o["stop"] if o["stop"] is not None else np.nan} for o in rep["open"]],
              {"symbol": "Stock", "entry_date": "Bought", "entry_price": "Fill ₹", "qty": "Qty",
               "last_price": "Now ₹", "value": "Value ₹", "pnl": "P&L ₹", "ret_pct": "Return %",
               "stop": "Stop ₹", "days": "Days"},
              signed=("pnl", "ret_pct"),
              fmt={"entry_price": "₹{:,.2f}", "last_price": "₹{:,.2f}", "value": "₹{:,.0f}", "pnl": "₹{:+,.0f}",
                   "ret_pct": "{:+.1f}", "stop": "₹{:,.2f}"},
              empty="The paper portfolio is in cash.")
        st.caption("P&L after buying charges, before selling charges. Fill = official open plus slippage.")
        st.subheader("Closed paper trades")
        table(rep["trades"][::-1], {"symbol": "Stock", "entry_date": "Bought", "entry_price": "Buy ₹",
                                    "exit_date": "Sold", "exit_price": "Sell ₹", "qty": "Qty", "pnl": "P&L ₹",
                                    "ret_pct": "Return %", "days": "Days", "reason": "Exit reason"},
              signed=("pnl", "ret_pct"),
              fmt={"entry_price": "₹{:,.2f}", "exit_price": "₹{:,.2f}", "pnl": "₹{:+,.0f}", "ret_pct": "{:+.1f}"},
              empty="No closed paper trades yet.")
        st.caption(f"Journal: {rep['journal_days']} scan day(s), {sm['start']} → {rep['last_journal']}; prices to "
                   f"{rep['last_date']}. Recomputed from the journal and stored prices on every view, so the same "
                   "data always gives the same answer.")

# ----------------------------------------------------------------------------- holdings
with tabs[3]:
    for h in latest["holdings"]:
        if h.get("alerts"):
            {"danger": st.error, "good": st.success}.get(h["level"], st.warning)(
                f"**{h['symbol']}** - " + " | ".join(h["alerts"]))
    table(latest["holdings"], {"symbol": "Stock", "qty": "Qty", "buy_price": "Buy ₹", "price": "Now ₹",
                               "change_pct": "Today %", "pnl_pct": "P&L %", "pnl_amount": "P&L ₹",
                               "stop_price": "Stop ₹", "target_price": "Target ₹",
                               "momentum_rank": "Momentum rank", "rs": "RS", "results_on": "Results on"},
          signed=("change_pct", "pnl_pct", "pnl_amount"),
          fmt={"buy_price": "₹{:,.2f}", "price": "₹{:,.2f}", "change_pct": "{:+.2f}", "pnl_pct": "{:+.1f}",
               "pnl_amount": "₹{:,.0f}", "stop_price": "₹{:,.2f}", "target_price": "₹{:,.2f}",
               "momentum_rank": "{:.0f}", "rs": "{:.0f}"},
          empty="Add your holdings below to get stop-loss, target and trend alerts.")
    st.subheader("Edit your holdings")
    hd = cfg.get("holdings_defaults") or {}
    st.caption(f"NSE symbols (e.g. RELIANCE, TCS, M&M). Add the **buy date** so splits/bonuses after you bought "
               f"are adjusted automatically. Empty stop/target % uses the defaults "
               f"({hd.get('stop_loss_pct', 8)}% / {hd.get('target_pct', 20)}%). Momentum rank 1 = strongest stock.")
    hold_df = load_holdings()
    hold_df["buy_date"] = pd.to_datetime(hold_df["buy_date"], errors="coerce")
    edited = st.data_editor(hold_df, num_rows="dynamic", hide_index=True, column_config={
        "symbol": st.column_config.TextColumn("Symbol", required=True),
        "qty": st.column_config.NumberColumn("Qty", min_value=0),
        "buy_price": st.column_config.NumberColumn("Buy price ₹", min_value=0, format="%.2f"),
        "buy_date": st.column_config.DateColumn("Buy date", format="DD MMM YYYY"),
        "stop_loss_pct": st.column_config.NumberColumn("Stop-loss %", min_value=0, max_value=100),
        "target_pct": st.column_config.NumberColumn("Target %", min_value=0, max_value=1000),
    })
    b1, b2 = st.columns([1, 2])
    if b1.button("💾 Save holdings"):
        save_holdings(edited)
        st.success("Saved. Click 🔄 Run scan now to refresh the alerts.")
    if b2.button("⬇️ Import my holdings from Fyers", help="Replaces the list with your Fyers demat holdings."):
        fy, note = get_fyers(cfg)
        fy_holdings = None
        if fy is None:
            st.error(note)
        else:
            try:
                fy_holdings = fy.holdings()
            except (FyersAuthError, FyersRateLimited) as e:   # expired token / FYERS budget protection
                st.error(f"Fyers holdings not available: {e}")
        if fy_holdings is not None:
            rows = [{"symbol": str(h.get("symbol", "")).split(":")[-1].rsplit("-", 1)[0],
                     "qty": h.get("quantity"), "buy_price": h.get("costPrice"), "buy_date": None,
                     "stop_loss_pct": None, "target_pct": None} for h in fy_holdings]
            if rows:
                save_holdings(pd.DataFrame(rows))
                st.success(f"Imported {len(rows)} holdings (Fyers cost prices are already split/bonus adjusted). "
                           "Run a scan to refresh the alerts.")
                st.rerun()
            else:
                st.warning("Fyers returned no holdings.")

# ----------------------------------------------------------------------------- market
with tabs[4]:
    cols = {"symbol": "Stock", "company": "Company", "price": "Price ₹", "change_pct": "Change %", "vol_ratio": "Volume ×"}
    f_ = {"price": "₹{:,.2f}", "change_pct": "{:+.2f}", "vol_ratio": "{:.1f}"}
    a, b = st.columns(2)
    with a:
        st.subheader("🚀 Top gainers")
        table(latest["gainers"], cols, signed=("change_pct",), fmt=f_)
    with b:
        st.subheader("📉 Top losers")
        table(latest["losers"], cols, signed=("change_pct",), fmt=f_)
    st.subheader("🔊 Unusual volume (3× normal or more)")
    table(latest["volume_spikes"], cols, signed=("change_pct",), fmt=f_)

# ----------------------------------------------------------------------------- chart
with tabs[5]:
    frames = cached_store(PanelStore().version())
    syms = [x for x in latest["symbols"] if x in frames["close"].columns]
    default = next((s_["ranking"][0]["symbol"] for s_ in strats if s_["ranking"]), syms[0] if syms else None)
    cc = st.columns([2, 3])
    sym = cc[0].selectbox("Stock", syms, index=syms.index(default) if default in syms else 0)
    period = cc[1].radio("Period", ["6M", "1Y", "2Y", "5Y"], index=1, horizontal=True)
    df = pd.DataFrame({k: frames[k][sym] for k in ("open", "high", "low", "close", "volume")}).dropna(subset=["close"])
    if df.empty:
        st.info("No data for this stock.")
    else:
        df = add_indicators(df)
        d = df.iloc[-{"6M": 126, "1Y": 252, "2Y": 504, "5Y": 1260}[period]:]
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.62, 0.16, 0.22], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=d.index, open=d["open"], high=d["high"], low=d["low"], close=d["close"],
                                     name="Price", increasing_line_color=GREEN, decreasing_line_color=RED), row=1, col=1)
        for col_, colr in (("sma20", "#f2a900"), ("sma50", "#2f7ed8"), ("sma200", "#8e44ad")):
            fig.add_trace(go.Scatter(x=d.index, y=d[col_], name=col_.replace("sma", "") + "-DMA",
                                     line=dict(width=1.3, color=colr)), row=1, col=1)
        fig.add_trace(go.Bar(x=d.index, y=d["volume"], name="Volume", marker_color="#9aa5b1"), row=2, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["rsi"], name="RSI 14", line=dict(color="#2f7ed8")), row=3, col=1)
        for lvl in (30, 70):
            fig.add_hline(y=lvl, line_dash="dot", line_color="#999", row=3, col=1)
        missing = pd.bdate_range(d.index[0], d.index[-1]).difference(d.index)
        fig.update_xaxes(rangebreaks=[dict(values=missing)])
        fig.update_layout(height=700, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10),
                          legend=dict(orientation="h", y=1.0, yanchor="bottom"))
        st.plotly_chart(fig)
        st.caption("Daily candles from the local store (split/bonus/demerger adjusted with NSE data).")

# ----------------------------------------------------------------------------- data & settings
with tabs[6]:
    st.write(f"**Live prices:** {latest['fyers_note']}")
    st.write(f"**Official data:** {latest['nse_status']} · complete through {latest['complete_upto']}")
    st.write(f"**{latest.get('results_note', 'Results calendar: -')}** (source: NSE event calendar)")
    st.write(f"**Trading cost assumed:** ~{latest['costs_round_trip_pct']}% per round trip on a typical position "
             "(edit the `costs:` section of config.yaml).")
    if latest["corporate_actions"]:
        st.write("**Price adjustments applied in the last update:**")
        table(latest["corporate_actions"], {"symbol": "Stock", "date": "Ex-date", "factor": "Factor", "reason": "Reason"},
              fmt={"factor": "{:.4f}"})
    if latest["errors"]:
        with st.expander(f"{len(latest['errors'])} symbols could not be downloaded"):
            st.write(latest["errors"])
    if latest["stale_symbols"]:
        st.caption("No fresh price on the latest day for: " + ", ".join(latest["stale_symbols"]))
    st.markdown("""
**How to read this**
- *Yearly return* is the compound annual growth rate (CAGR) of the strategy's model portfolio.
- *Worst drop* is the largest fall from a peak. Expect to live through drops like this.
- *Win rate* alone means little. Momentum wins under half its trades but its winners are much bigger than its losers.
- Signals use the close of day *t* and trade at the open of day *t+1*. No future data is used.
- **Survivorship bias:** the stock list is today's index list, so past results look better than reality.
  Compare against the *average stock* line, not just Nifty.
""")
