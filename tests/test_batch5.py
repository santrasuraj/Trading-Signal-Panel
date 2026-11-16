"""Practice bot, Telegram setups and brief, company screener, results study, sector rotation, volatility, F&O symbol
parsing, intraday templates, rebalancing, Excel export. Synthetic data in temporary folders; nothing is sent."""
import io
import json
import zipfile
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from scanner.settings import IST
from web.api.paths import P


# ---- practice bot ----------------------------------------------------------------------------------------------------
@pytest.fixture
def bot_env(tmp_path, monkeypatch):
    from web.api.services import bot_svc, clock, data, quotes_svc, sim_svc
    monkeypatch.setattr(P, "data", tmp_path)
    lt = {"generated_at": "s1", "strategies": [{"key": "mom", "name": "Momentum", "status": "working", "max_positions": 2,
                                                "positions": [{"symbol": "OLD", "entry_price": 50}]}]}
    monkeypatch.setattr(data, "latest", lambda: lt)
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 100_000}, "costs": {"slippage_pct": 0}})
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "open"})
    now = datetime(2026, 11, 12, 10, 0, tzinfo=IST)
    monkeypatch.setattr(bot_svc, "now_ist", lambda: now)
    monkeypatch.setattr(sim_svc, "now_ist", lambda: now)
    prices = {"OLD": 50.0, "NEW": 100.0}
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, allow_network=True: {
        "session": "open", "quotes": [{"symbol": s, "price": prices[s], "source": "live"} for s in syms if s in prices]})
    return bot_svc, lt, prices


def test_bot_mirrors_new_entries_and_exits_only(bot_env):
    bot, lt, prices = bot_env
    bot.settings(["mom"], 100_000)
    r = bot.reconcile()
    assert r["ran"] and r["orders"] == 0                         # OLD was held before the bot started: skipped
    lt["strategies"][0]["positions"].append({"symbol": "NEW", "entry_price": 98.0})
    lt["generated_at"] = "s2"
    r = bot.reconcile()
    assert r["orders"] == 1
    v = bot.view()
    rec = next(s for s in v["strategies"] if s["key"] == "mom")["record"]
    assert rec["open"][0]["symbol"] == "NEW" and rec["open"][0]["qty"] == 500          # 1 lakh / 2 slots / Rs 100
    assert rec["avg_entry_vs_model_pct"] == pytest.approx((100 / 98 - 1) * 100, abs=0.01)
    lt["strategies"][0]["positions"] = [p for p in lt["strategies"][0]["positions"] if p["symbol"] != "NEW"]
    lt["generated_at"] = "s3"
    prices["NEW"] = 110.0
    assert bot.reconcile()["orders"] == 1
    rec = next(s for s in bot.view()["strategies"] if s["key"] == "mom")["record"]
    assert rec["closed"] == 1 and rec["realised"] == pytest.approx(5000) and rec["open"] == []


def test_bot_waits_for_0920(bot_env, monkeypatch):
    bot, _, _ = bot_env
    bot.settings(["mom"], 100_000)
    monkeypatch.setattr(bot, "now_ist", lambda: datetime(2026, 11, 12, 9, 16, tzinfo=IST))
    assert not bot.reconcile()["ran"]


# ---- Telegram: live setups and the brief -----------------------------------------------------------------------------
def test_setups_go_to_telegram_once(tmp_path, monkeypatch):
    from scanner import settings as st
    from scanner.intraday import setups
    import scanner.intraday.live as live
    monkeypatch.setattr(st, "DATA_DIR", tmp_path)
    root = tmp_path / "intraday"
    monkeypatch.setattr(live, "live_dir", lambda r: (r / "live").mkdir(parents=True, exist_ok=True) or r / "live")
    day = date(2026, 11, 12)
    ts = pd.date_range("2026-11-12 09:15", periods=10, freq="5min")
    c = np.array([103.0] * 9 + [104.0])
    bars = pd.DataFrame({"ts": ts, "symbol": "TCS", "open": c, "high": c + 0.1, "low": c - 0.1, "close": c,
                         "volume": 1e4, "flags": 0})
    live.live_file(root, day).parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(live.live_file(root, day))
    setups._prev_cache.clear()
    store = {"close": pd.DataFrame({"TCS": [100.0]}, index=[pd.Timestamp("2026-11-11")]),
             "high": pd.DataFrame({"TCS": [101.0]}, index=[pd.Timestamp("2026-11-11")]),
             "low": pd.DataFrame({"TCS": [99.0]}, index=[pd.Timestamp("2026-11-11")])}
    monkeypatch.setattr(setups, "_mine", lambda: {"TCS"})
    sent = []
    cfg = {"setups": {"on": True, "scope": "mine", "kinds": ["gap_up"]}}
    n = setups.telegram_new(root, day, cfg, send=lambda t: (sent.append(t), (True, "sent"))[1], store=store)
    assert n == 1 and "Gap up" in sent[0]
    assert setups.telegram_new(root, day, cfg, send=lambda t: (sent.append(t), (True, "sent"))[1], store=store) == 0
    assert setups.telegram_new(root, day, {"setups": {"on": False}}) == 0


def test_notify_settings_default_off(tmp_path, monkeypatch):
    from scanner import notify_settings as ns
    monkeypatch.setattr(ns, "DATA_DIR", tmp_path)
    assert ns.read()["brief"] is False and ns.read()["setups"]["on"] is False
    ns.write({"brief": True, "setups": {"on": True, "scope": "all"}})
    v = ns.read()
    assert v["brief"] and v["setups"]["on"] and v["setups"]["scope"] == "all"


# ---- results study, sector rotation, volatility ----------------------------------------------------------------------
def test_results_event_reaction_and_drift():
    from scanner import results_study as rs
    idx = pd.bdate_range("2026-01-01", periods=120)
    flat = {f"F{i}": np.full(120, 50.0) for i in range(9)}     # A is 1 of 10, as in a real universe it barely moves the average
    close = pd.DataFrame({"A": np.r_[np.full(60, 100.0), np.linspace(110, 130, 60)], **flat}, index=idx)
    member = close.notna()
    ev = rs.events_table(close, member, [("A", idx[60])])
    row = ev.iloc[0]
    a = close["A"]
    bench = (1 + a.pct_change().iloc[60:62] / 10).prod()        # the average stock (A included) over the same closes
    assert row["reaction"] == pytest.approx((a.iat[61] / a.iat[59] - bench) * 100)   # close before the day -> after
    assert row["bucket"] == "Rose over 6%" and row["fwd_20"] > 0
    assert rs.bucket(-7) == "Fell over 6%" and rs.bucket(0.5) == "Within 2%"


def test_rrg_quadrants():
    from web.api.services import rrg_svc
    assert rrg_svc.quadrant(101, 101) == "Leading" and rrg_svc.quadrant(101, 99) == "Weakening"
    assert rrg_svc.quadrant(99, 99) == "Lagging" and rrg_svc.quadrant(99, 101) == "Improving"
    idx = pd.bdate_range("2024-01-01", periods=80, freq="W-FRI")
    bench = pd.Series(np.linspace(100, 120, 80), index=idx)
    px = pd.DataFrame({"Strong": bench * np.linspace(1, 1.5, 80), "Weak": bench * np.linspace(1, 0.7, 80)}, index=idx)
    ratio, mom = rrg_svc.rrg_frames(px, bench)
    assert ratio["Strong"].iloc[-1] > 100 > ratio["Weak"].iloc[-1]
    rec = rrg_svc.record(px, bench, ratio, mom)
    assert {r["quadrant"] for r in rec} == {"Leading", "Weakening", "Lagging", "Improving"}


def test_vix_record_counts_quieter_months():
    from web.api.services import vol_svc
    idx = pd.bdate_range("2020-01-01", periods=700)
    rng = np.random.default_rng(3)
    nifty = pd.Series(10000 * np.exp(np.cumsum(rng.normal(0, 0.01, 700))), index=idx)     # ~16% a year realised
    vix = pd.Series(20.0, index=idx)
    r = vol_svc.record(vix, nifty)
    assert r["below_pct"] > 70 and r["gap_avg"] > 0 and r["by_percentile"]


# ---- F&O symbols, intraday templates, rebalancing, export ------------------------------------------------------------
def test_fyers_fno_symbols():
    from web.api.services.payoff_svc import parse_fno_symbol as p
    assert p("NSE:NIFTY26NOV25200CE") == {"underlying": "NIFTY", "kind": "CE", "strike": 25200.0, "expiry": None, "monthly": (2026, 11)}
    assert p("NSE:NIFTY26D0125000PE")["expiry"] == "2026-12-01"
    assert p("NSE:BANKNIFTY26DECFUT")["kind"] == "FUT" and p("NSE:TCS-EQ") is None


def test_orb_template_trades_the_first_break():
    from scanner.intraday import custom
    from scanner.intraday.engine import SLOTS, Day
    c = np.full(SLOTS, 100.0)
    h, l = c + 0.5, c - 0.5
    h[5], c[5] = 103.0, 102.5                 # breaks the 15-minute high (100.5) at 09:40
    d = Day("TCS", pd.Timestamp("2026-11-12"), c.copy(), h, l, c, np.full(SLOTS, 1e4), 100.0, 101.0, 99.0, 2.0, True, True)
    t = custom.strategy({"template": "orb", "direction": "both", "or_minutes": 15, "stop": "range", "target_r": 1,
                         "cutoff_min": 780}).day_trades(d, {"or_minutes": 15, "direction": "both", "target_r": 1, "cutoff_min": 780})
    assert len(t) == 1 and t[0].side == 1 and t[0].entry_px == pytest.approx(100.5) and t[0].stop == pytest.approx(99.5)


def test_rebalance_equal_weight_and_tax():
    from web.api.services import rebalance_svc
    h = pd.DataFrame({"symbol": ["A", "B"], "qty": [300, 100], "buy_price": [80.0, 100.0],
                      "buy_date": [date(2024, 1, 1), date(2026, 6, 1)], "stop_loss_pct": [None, None], "target_pct": [None, None]})
    p = rebalance_svc.plan(h, {"A": 100.0, "B": 100.0}, pd.DataFrame(), "equal", min_trade=0, today=date(2026, 11, 12))
    rows = {r["symbol"]: r for r in p["rows"]}
    assert rows["A"]["side"] == "SELL" and rows["A"]["trade_qty"] == 100 and rows["B"]["trade_qty"] == 100
    assert rows["A"]["gain_lt"] == pytest.approx(2000) and p["totals"]["tax_if_alone"] == 0   # inside the exemption
    with pytest.raises(Exception):
        rebalance_svc.plan(h, {"A": 100.0, "B": 100.0}, pd.DataFrame(), "custom", custom={"A": 80, "B": 40})


def test_xlsx_workbook_is_valid():
    from web.api.services import export_svc
    b = export_svc.xlsx({"Lots": [{"symbol": "TCS", "qty": 10, "ok": True, "note": "a & b <c>"}], "Empty": []})
    z = zipfile.ZipFile(io.BytesIO(b))
    import xml.dom.minidom
    for n in z.namelist():
        xml.dom.minidom.parseString(z.read(n))
    s1 = z.read("xl/worksheets/sheet1.xml").decode()
    assert "a &amp; b &lt;c&gt;" in s1 and '<v>10</v>' in s1 and 't="b"' in s1
    assert 'name="Lots"' in z.read("xl/workbook.xml").decode()
