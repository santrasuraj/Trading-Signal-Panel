"""Web dashboard.  Run:  streamlit run dashboard.py   (or double-click 3_dashboard.bat)"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from scanner.backtest import load_backtest, run_backtest
from scanner.data import load_cached
from scanner.indicators import add_indicators
from scanner.providers import load_token
from scanner.rules import active_rules
from scanner.scan import HOLDING_COLS, load_holdings, load_latest, run_scan
from scanner.settings import HOLDINGS_FILE, ist_today, load_config

st.set_page_config(page_title="NSE Stock Scanner", page_icon="📈", layout="wide")

DISCLAIMER = ("These are automatic, rule-based signals - not investment advice. Rules are often wrong on "
              "individual trades. Always check the chart, use a stop-loss, and decide yourself.")

cfg = load_config()


def fmt_time(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %Y, %I:%M %p")


def color_change(v):
    if v is None or pd.isna(v):
        return ""
    return "color: #1a9e55" if v > 0 else "color: #d43c3c" if v < 0 else ""


def show_table(rows: list[dict], columns: dict[str, str], height: int | None = None):
    """columns = {source_key: display_name}. Formats rupee / % / ratio columns."""
    if not rows:
        st.info("Nothing here right now.")
        return
    df = pd.DataFrame(rows)
    for k in columns:
        if k not in df.columns:
            df[k] = None
    df = df[list(columns)].rename(columns=columns)
    for c in df.columns:
        if df[c].map(lambda x: isinstance(x, list)).any():
            df[c] = df[c].map(lambda x: " • ".join(x) if isinstance(x, list) else x)
    fmt = {}
    for c in df.columns:
        if "₹" in c:
            fmt[c] = "₹{:,.2f}"
        elif "%" in c:
            fmt[c] = "{:+.2f}%" if "Chg" in c or "P&L" in c else "{:.0f}%"
        elif "×" in c:
            fmt[c] = "{:.1f}×"
        elif c == "RSI":
            fmt[c] = "{:.0f}"
    styler = df.style.format(fmt, na_rep="-")
    chg_cols = [c for c in df.columns if "Chg" in c or "P&L" in c]
    if chg_cols:
        styler = styler.map(color_change, subset=chg_cols)
    st.dataframe(styler, hide_index=True, **({"height": height} if height else {}))


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("📈 NSE Scanner")
    tok = load_token()
    if tok and tok.get("created", "")[:10] == ist_today().isoformat():
        st.success("Fyers token from today ✓")
    else:
        st.warning("Not logged in to Fyers today - run **1_login.bat** for live data. "
                   "Until then, delayed Yahoo data is used.")

    if st.button("🔄 Run scan now", type="primary"):
        bar = st.progress(0.0, text="Starting...")
        status = st.empty()

        def prog(done, total, sym):
            bar.progress(min(done / max(total, 1), 1.0), text=f"Downloading {sym} ({done}/{total})")

        try:
            run_scan(cfg, progress=prog, log=lambda m: status.caption(m))
            st.rerun()
        except Exception as e:
            st.error(f"Scan failed: {e}")

    latest = load_latest()
    if st.button("🧪 Run backtest", disabled=latest is None,
                 help="Tests every rule on the last 2 years of data (uses already-downloaded prices)."):
        bar = st.progress(0.0, text="Backtesting...")
        try:
            run_backtest(cfg, latest["source_name"],
                         progress=lambda d, t, s: bar.progress(d / t, text=f"Testing {s} ({d}/{t})"))
            run_scan(cfg, update=False, log=lambda m: None)  # attach new win-rates to the signals
            st.rerun()
        except Exception as e:
            st.error(f"Backtest failed: {e}")

    if latest:
        st.divider()
        st.caption(f"**Last scan:** {fmt_time(latest['generated_at'])}")
        st.caption(f"**Prices as of:** {latest['data_date']}{' (market open - live)' if latest.get('live') else ''}")
        st.caption(f"**Source:** {latest['source']}")
        st.caption(f"**Universe:** {latest['universe']} · {latest['stocks_scanned']} scanned")
    st.divider()
    st.caption(DISCLAIMER)

# ------------------------------------------------------------------ main
if not latest:
    st.header("Welcome 👋")
    st.write("No scan yet. Click **🔄 Run scan now** in the left panel. "
             "The first scan downloads ~3 years of prices for every stock (Fyers: ~10 min, Yahoo: ~2 min). "
             "After that, scans take seconds.")
    st.stop()

m = latest.get("market", {})
banner = {"good": st.success, "bad": st.error}.get(m.get("level"), st.warning)
banner(f"**Market mood: {m.get('label', '?')}** - {m.get('advice', '')}")
if latest.get("live"):
    st.info("⏱ Market is open. Today's candle is still forming - signals can change before 3:30 PM. "
            "Volume is projected to a full day.")
if "Yahoo" in latest["source"] and latest.get("source_note"):
    st.caption(f"ℹ️ {latest['source_note']}")

c = st.columns(5)
c[0].metric("Nifty 50", f"{m.get('nifty') or 0:,.0f}", f"{m.get('nifty_change_pct') or 0:+.2f}%")
c[1].metric("India VIX", f"{m.get('vix') or 0:.1f}", f"{m.get('vix_change_pct') or 0:+.2f}%", delta_color="inverse")
c[2].metric("Above 50-DMA", f"{m.get('breadth_50') or 0:.0f}%", help="% of scanned stocks above their 50-day average")
c[3].metric("Up / Down", f"{m.get('advances', 0)}/{m.get('declines', 0)}", help="Stocks that rose / fell today")
c[4].metric("Buy / Sell", f"{len(latest['buy'])}/{len(latest['sell'])}", help="Number of buy / sell signals")

tabs = st.tabs(["🟢 Buy signals", "🔴 Sell signals", "💼 My holdings", "📊 Today's movers",
                "🧪 Backtest", "📈 Chart"])

# ---- Buy
with tabs[0]:
    if m.get("level") == "bad":
        st.error("⚠️ The overall market is falling. Buy signals fail much more often in this condition.")
    if not latest.get("backtest_available"):
        st.caption("Tip: click **🧪 Run backtest** once to see how often each rule worked in the past.")
    st.caption("Sorted by number of rules agreeing, then volume. Stop-loss / target use your % from config.yaml.")
    show_table(latest["buy"], {
        "symbol": "Stock", "company": "Company", "close": "Price ₹", "change_pct": "Chg %",
        "signals": "Signals", "reasons": "Why", "vol_ratio": "Volume ×", "rsi": "RSI",
        "stop_loss": "Stop-loss ₹", "target": "Target ₹", "backtest_win_rate": "Past win %",
    })

# ---- Sell
with tabs[1]:
    st.caption("Stocks showing weakness. Useful for exiting holdings or avoiding new buys.")
    show_table(latest["sell"], {
        "symbol": "Stock", "company": "Company", "close": "Price ₹", "change_pct": "Chg %",
        "signals": "Signals", "reasons": "Why", "vol_ratio": "Volume ×", "rsi": "RSI",
        "backtest_win_rate": "Past hit %",
    })

# ---- Holdings
with tabs[2]:
    hold = latest.get("holdings", [])
    for h in hold:
        if h.get("alerts"):
            box = {"danger": st.error, "good": st.success}.get(h["level"], st.warning)
            box(f"**{h['symbol']}** - " + " | ".join(h["alerts"]))
    show_table(hold, {
        "symbol": "Stock", "qty": "Qty", "buy_price": "Buy ₹", "close": "Now ₹", "change_pct": "Today Chg %",
        "pnl_pct": "P&L %", "pnl_amount": "P&L ₹", "stop_price": "Stop ₹", "target_price": "Target ₹",
    })
    st.subheader("Edit your holdings")
    st.caption("Use NSE symbols (e.g. RELIANCE, TCS, M&M). Leave stop/target % empty to use the defaults "
               f"({cfg['holdings_defaults']['stop_loss_pct']}% / {cfg['holdings_defaults']['target_pct']}%).")
    edited = st.data_editor(load_holdings(), num_rows="dynamic", hide_index=True, column_config={
        "symbol": st.column_config.TextColumn("Symbol", required=True),
        "qty": st.column_config.NumberColumn("Qty", min_value=0),
        "buy_price": st.column_config.NumberColumn("Buy price ₹", min_value=0, format="%.2f"),
        "stop_loss_pct": st.column_config.NumberColumn("Stop-loss %", min_value=0, max_value=100),
        "target_pct": st.column_config.NumberColumn("Target %", min_value=0, max_value=1000),
    })
    if st.button("💾 Save holdings"):
        out = edited.copy()
        out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
        out[out["symbol"].ne("") & out["symbol"].ne("NAN")][HOLDING_COLS].to_csv(HOLDINGS_FILE, index=False)
        st.success("Saved. Click 🔄 Run scan now to update the alerts.")

# ---- Movers
with tabs[3]:
    cols = {"symbol": "Stock", "close": "Price ₹", "change_pct": "Chg %", "vol_ratio": "Volume ×"}
    a, b = st.columns(2)
    with a:
        st.subheader("🚀 Top gainers")
        show_table(latest["gainers"], cols)
    with b:
        st.subheader("📉 Top losers")
        show_table(latest["losers"], cols)
    st.subheader("🔊 Volume spikes (3× normal volume or more)")
    show_table(latest["volume_spikes"], {"symbol": "Stock", "company": "Company", **{k: v for k, v in cols.items() if k != "symbol"}})

# ---- Backtest
with tabs[4]:
    bt = load_backtest()
    if not bt:
        st.info("No backtest yet. Click **🧪 Run backtest** in the left panel (takes ~1 minute).")
    else:
        s = bt["settings"]
        st.write(f"Tested on **{bt['stocks_tested']} stocks**, last **{s['years']:g} years**. "
                 f"BUY rules: buy next morning, exit at −{s['stop_loss_pct']:g}% stop / +{s['target_pct']:g}% target "
                 f"or after {s['max_hold_days']} days, after {s['cost_pct']}% costs. "
                 f"SELL rules: % of times the stock fell over the next {s['max_hold_days']} days.")
        st.write(f"**Baseline** (buying every stock on every day): avg {bt['baseline']['avg_return']:+.2f}% per trade, "
                 f"up {bt['baseline']['pct_up']:.0f}% of the time. A rule is only useful if it beats this.")
        for side in ("BUY", "SELL"):
            st.subheader(f"{side} rules")
            rows = [r for r in bt["rules"] if r["side"] == side]
            show_table(rows, {
                "name": "Rule", "verdict": "Verdict", "signals": "Signals",
                "win_rate": "Win %" if side == "BUY" else "Fell %",
                "avg_return": "Avg Chg %", "median_return": "Median Chg %",
                "edge": "Edge vs baseline Chg %", "explain": "What it means",
            })
        st.caption(f"Backtest run {fmt_time(bt['generated_at'])}. Past results don't guarantee future results. "
                   "Turn off rules with no edge in config.yaml (enabled: false).")

# ---- Chart
with tabs[5]:
    snap = latest.get("snapshot", [])
    syms = sorted(s["symbol"] for s in snap)
    if syms:
        default = latest["buy"][0]["symbol"] if latest["buy"] else syms[0]
        cc = st.columns([2, 3])
        sym = cc[0].selectbox("Stock", syms, index=syms.index(default) if default in syms else 0)
        period = cc[1].radio("Period", ["3M", "6M", "1Y", "2Y"], index=1, horizontal=True)
        raw = load_cached(latest["source_name"], [sym])[sym]
        if raw.empty:
            st.info("No saved history for this stock yet.")
        else:
            df = add_indicators(raw)
            marks = {"BUY": pd.Series(False, index=df.index), "SELL": pd.Series(False, index=df.index)}
            for rule, params in active_rules(cfg):
                marks[rule.side] |= rule.evaluate(df, params)
            days = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 504}[period]
            d = df.iloc[-days:]
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.18, 0.22],
                                vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=d.index, open=d["open"], high=d["high"], low=d["low"], close=d["close"],
                                         name="Price", increasing_line_color="#1a9e55",
                                         decreasing_line_color="#d43c3c"), row=1, col=1)
            for col, colr in (("sma20", "#f2a900"), ("sma50", "#2f7ed8"), ("sma200", "#8e44ad")):
                fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col.upper().replace("SMA", "") + "-DMA",
                                         line=dict(width=1.3, color=colr)), row=1, col=1)
            b, s_ = d[marks["BUY"].loc[d.index]], d[marks["SELL"].loc[d.index]]
            fig.add_trace(go.Scatter(x=b.index, y=b["low"] * 0.98, mode="markers", name="Buy signal",
                                     marker=dict(symbol="triangle-up", size=11, color="#1a9e55")), row=1, col=1)
            fig.add_trace(go.Scatter(x=s_.index, y=s_["high"] * 1.02, mode="markers", name="Sell signal",
                                     marker=dict(symbol="triangle-down", size=11, color="#d43c3c")), row=1, col=1)
            fig.add_trace(go.Bar(x=d.index, y=d["volume"], name="Volume", marker_color="#9aa5b1"), row=2, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=d["rsi"], name="RSI", line=dict(color="#2f7ed8")), row=3, col=1)
            for lvl in (30, 70):
                fig.add_hline(y=lvl, line_dash="dot", line_color="#999", row=3, col=1)
            missing = pd.bdate_range(d.index[0], d.index[-1]).difference(d.index)
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]), dict(values=missing)])
            fig.update_layout(height=720, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10),
                              legend=dict(orientation="h", y=1.0, yanchor="bottom"))
            st.plotly_chart(fig)
            st.caption("Completed daily candles. ▲ / ▼ = days when any enabled buy / sell rule fired - "
                       "look at how they played out before trusting them.")

if latest.get("errors"):
    with st.expander(f"⚠️ {len(latest['errors'])} symbols had download problems"):
        st.write(latest["errors"])
