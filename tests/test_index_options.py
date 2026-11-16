"""Index options (scanner/option_verdict.py index path, web/api/services/options_svc.indices): every NSE index with
options gets the daily verdict from its own NSE history and settles at NSE's official index close. Synthetic data."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scanner import option_verdict as ov


def ih_frame():
    idx = pd.bdate_range("2026-01-01", "2026-11-13")
    return pd.DataFrame({"Nifty 50": np.linspace(23000, 25144.3, len(idx)),
                         "Nifty Bank": np.linspace(50000, 61034.1, len(idx))}, index=idx)


def test_every_nse_index_with_options_has_an_index_column():
    assert set(ov.INDEX_COLUMN) == {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def test_index_close_comes_from_nse_history_with_the_stores_newer_close_on_top():
    ih = ih_frame()
    s = ov.index_close("BANKNIFTY", ih)
    assert s.index[-1] == pd.Timestamp("2026-11-13") and s.iloc[-1] == pytest.approx(61034.1)
    store = pd.DataFrame({"NIFTY50": [25100.0, 25300.0]}, index=pd.to_datetime(["2026-11-13", "2026-11-16"]))
    n = ov.index_close("NIFTY", ih, store)
    assert n.index[-1] == pd.Timestamp("2026-11-16") and n.iloc[-1] == 25300.0      # only the newer day is added
    assert n.loc["2026-11-13"] == pytest.approx(25144.3)                             # NSE's own close kept
    assert ov.index_close("FINNIFTY", ih) is None                                    # not in this history


def test_an_index_the_store_lacks_settles_at_nses_official_close():
    row = {"id": "x", "day": "2026-11-03", "symbol": "BANKNIFTY", "store_symbol": "Nifty Bank", "expiry": "2026-11-10",
           "spot": 55000.0, "verdict": "BUY_CALL", "side": "ce", "strike": 55000.0, "premium": 500.0, "breakeven": 55500.0,
           "atm_call": {"strike": 55000.0, "premium": 500.0}, "atm_put": {"strike": 55000.0, "premium": 480.0}}
    closes = {"BANKNIFTY": pd.Series([55400.0, 56100.0], index=pd.to_datetime(["2026-11-09", "2026-11-10"]))}
    (r,) = ov.score([row], {}, today=date(2026, 11, 14), index_closes=closes)
    assert r["settled"] and r["settle_price"] == 56100.0 and r["pick_return_pct"] > 0


def test_journal_keeps_the_headline_and_the_direction(tmp_path, monkeypatch):
    monkeypatch.setattr(ov, "JOURNAL_FILE", tmp_path / "option_verdicts.json")
    v = {"symbol": "FINNIFTY", "store_symbol": "Nifty Financial Services", "expiry": "2026-11-23", "spot": 27000.0,
         "verdict": "NO_TRADE", "headline": "No options edge: tested direction failed.", "direction": {"bias": "none"},
         "calls": [{"strike": 27000.0, "premium": 300.0}], "puts": [{"strike": 27000.0, "premium": 280.0}], "pick": None}
    ov.record([v], "2026-11-16")
    (row,) = ov.load_journal()
    assert row["headline"].startswith("No options edge") and row["bias"] == "none" and row["symbol"] == "FINNIFTY"


# ---- exact option charges -------------------------------------------------------------------------------------------
def test_exact_buy_cost_from_the_official_rates_and_the_lot_size():
    # NIFTY ATM call at Rs 137.75, lot 65: premium + 0.03503% NSE + 0.0001% SEBI (both + 18% GST) + 0.003% stamp
    # + Rs 20 brokerage + 18% GST spread over 65 units
    want = 137.75 * (1 + (0.03503 + 0.0001) / 100 * 1.18 + 0.003 / 100) + 20 * 1.18 / 65
    assert ov.buy_cost(137.75, 65) == pytest.approx(want)
    assert (ov.buy_cost(137.75, 65) / 137.75 - 1) * 100 == pytest.approx(0.31, abs=0.01)    # not the old 3% guess
    assert ov.buy_cost(137.75, None) == pytest.approx(137.75 * 1.03)                        # no lot: the estimate


def test_expiry_value_charges_only_an_option_that_finishes_in_the_money():
    pay = np.array([0.0, 100.0])
    got = ov.expiry_value(pay, 65)
    assert got[0] == 0.0                                                                     # expires worthless: no charges
    assert got[1] == pytest.approx(100 * (1 - 0.00125) - 20 * 1.18 / 65)                     # exercise STT + brokerage


def test_breakeven_and_return_include_the_exercise_charges():
    cost = ov.buy_cost(137.75, 65)
    be = ov._breakeven("ce", 25150.0, cost, 65)
    assert float(ov.expiry_value(be - 25150.0, 65)) == pytest.approx(cost)                  # pays back exactly at breakeven
    assert ov._payoff("ce", 25150.0, 137.75, be, 65) == pytest.approx(0.0, abs=1e-9)
    assert ov._payoff("ce", 25150.0, 137.75, 25000.0, 65) == pytest.approx(-100.0)          # worthless: lose it all


def test_index_options_endpoint_lists_each_index_with_its_latest_verdict(monkeypatch):
    from web.api.services import data, options_svc as svc
    refs = [{"symbol": "NIFTY", "expiry": "2026-11-17", "day": "2026-11-13"},
            {"symbol": "NIFTY", "expiry": "2026-11-23", "day": "2026-11-13"},
            {"symbol": "NIFTY", "expiry": "2026-12-29", "day": "2026-11-13"},       # a third expiry: left out
            {"symbol": "RELIANCE", "expiry": "2026-11-23", "day": "2026-11-13"}]    # a stock: not an index row
    monkeypatch.setattr(svc, "_refs", lambda: refs)
    monkeypatch.setattr(svc, "_cfg", lambda: {"underlyings": ["NIFTY", "BANKNIFTY", "RELIANCE"], "risk_free_pct": 6.5})
    chain = {"days_to_expiry": 3.6, "spot": 25144.3, "time": "2026-11-13T15:40:00+05:30", "stale": False, "atm": 25150.0,
             "summary": {"atm_iv_pct": 13.1, "expected_move_pct": 1.09, "range_low": 24870.0, "range_high": 25420.0,
                         "pcr_oi": 0.83, "max_pain": 25200.0},
             "rows": [{"strike": 25150.0, "atm": True, "ce": {"ltp": 137.75}, "pe": {"ltp": 136.6}}]}
    monkeypatch.setattr(svc, "chain", lambda s, e, w: chain)
    journal = [{"symbol": "NIFTY", "expiry": "2026-11-17", "day": "2026-11-12", "verdict": "NO_TRADE",
                "atm_call": {"strike": 25300.0, "premium": 203.9}, "atm_put": {"strike": 25300.0, "premium": 192.5}},
               {"symbol": "NIFTY", "expiry": "2026-11-17", "day": "2026-11-13", "verdict": "BUY_PUT", "side": "pe",
                "strike": 25100.0, "premium": 120.0, "breakeven": 24980.0, "headline": "BUY PUT ...", "bias": "bearish",
                "atm_call": {"strike": 25150.0, "premium": 137.75}, "atm_put": {"strike": 25150.0, "premium": 136.6}}]
    monkeypatch.setattr(svc._journal, "get", lambda p: journal)
    monkeypatch.setattr(data, "store_close", lambda: pd.DataFrame())
    out = svc.indices()
    assert [(r["symbol"], r["expiry"]) for r in out["rows"]] == [("NIFTY", "2026-11-17"), ("NIFTY", "2026-11-23")]
    first, second = out["rows"]
    assert first["verdict"] == "BUY_PUT" and first["verdict_day"] == "2026-11-13" and first["pick"]["strike"] == 25100.0
    assert first["atm_call"] == 137.75 and first["expected_move_pct"] == 1.09
    assert second["verdict"] is None                                                 # not journalled yet
    assert out["missing"] == ["BANKNIFTY"] and "SEBI" in out["note"]


# ---- better verdicts: the plan, the closest option, every check, every index ---------------------------------------
def _fwd_chain(spot=25000.0, days=10.0):
    return {"forward": spot * 1.002, "spot": spot, "days_to_expiry": days}


def test_a_buy_pick_comes_with_its_trade_in_premiums():
    c = _fwd_chain()
    fair = ov.premium_at(c, 25000.0, "ce", 14.0, 25000.0, 0.0)
    pick = {"strike": 25000.0, "side": "ce", "iv_pct": 14.0, "premium": round(fair * 1.01, 2)}
    p = ov.plan(c, pick, {"stop_underlying": 24800.0, "target_underlying": 25300.0}, 65, 5)
    assert p["stop"] < p["entry"] < p["target"] and p["hold_days"] == 7.0              # 5 trading days = 7 calendar
    assert p["capital"] == pytest.approx(ov.buy_cost(p["entry"], 65) * 65, abs=0.01)
    assert p["max_loss"] == p["capital"]                                              # a gap can jump the stop
    assert 0 < p["loss_at_stop"] < p["max_loss"] and p["gain_at_target"] > 0
    put = ov.plan(c, {**pick, "side": "pe"}, {"stop_underlying": 25200.0, "target_underlying": 24700.0}, 65, 5)
    assert put["stop"] < put["entry"] < put["target"]
    no_iv = ov.plan(c, {**pick, "iv_pct": None}, {"stop_underlying": 24800.0, "target_underlying": 25300.0}, 65, 5)
    assert no_iv["stop"] is None and no_iv["target"] is None and no_iv["capital"] is not None


def test_selling_an_option_pays_its_charges():
    assert ov.sell_value(100.0, 65) == pytest.approx(100 * (1 - 0.001 - (0.03503 + 0.0001) / 100 * 1.18) - 20 * 1.18 / 65)
    assert ov.sell_value(100.0, None) == pytest.approx(97.0)


def test_journal_keeps_the_checks_the_reasons_the_closest_option_and_the_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(ov, "JOURNAL_FILE", tmp_path / "option_verdicts.json")
    closest = {"side": "ce", "strike": 27000.0, "premium": 300.0, "fair": 330.0, "edge_pct": 9.0, "prob_profit_pct": 38.0,
               "breakeven": 27310.0, "ok": False, "fails": ["history-fair value only +9% vs the price paid (needs +10%)"],
               "bid": 299.0, "quoted": True}
    v = {"symbol": "FINNIFTY", "expiry": "2026-11-23", "spot": 27000.0, "verdict": "NO_TRADE", "headline": "No options edge",
         "direction": {"bias": "none", "reasons": ["Similar setups: no usable direction."]},
         "checks": [{"name": "Tested direction", "ok": False, "detail": "none"}], "closest": closest, "plan": None,
         "calls": [{"strike": 27000.0, "premium": 300.0}], "puts": [], "pick": None, "journal_day": "2026-11-13"}
    ov.record([v], "2026-11-15")
    (row,) = ov.load_journal()
    assert row["day"] == "2026-11-13" and row["id"] == "FINNIFTY|2026-11-23|2026-11-13"   # the chain's session
    assert row["checks"] == [{"name": "Tested direction", "ok": False, "detail": "none"}]
    assert row["reasons"] == ["Similar setups: no usable direction."]
    assert row["closest"]["strike"] == 27000.0 and "bid" not in row["closest"]          # compact


def test_the_closest_option_of_a_no_trade_is_scored_too():
    base = {"id": "x", "day": "2026-11-03", "symbol": "BANKNIFTY", "expiry": "2026-11-10", "spot": 55000.0, "lot": 30,
            "atm_call": {"strike": 55000.0, "premium": 500.0}, "atm_put": {"strike": 55000.0, "premium": 480.0}}
    rows = [{**base, "verdict": "NO_TRADE", "closest": {"side": "ce", "strike": 55000.0, "premium": 500.0}},
            {**base, "id": "y", "verdict": "NO_TRADE", "closest": {"side": "pe", "strike": 55000.0, "premium": 480.0}},
            {**base, "id": "z", "verdict": "NO_DATA", "closest": {"side": "ce", "strike": 55000.0, "premium": 500.0}}]
    closes = {"BANKNIFTY": pd.Series([56100.0], index=pd.to_datetime(["2026-11-10"]))}
    a, b, c = ov.score(rows, {}, today=date(2026, 11, 14), index_closes=closes)
    assert a["closest_return_pct"] > 0 and b["closest_return_pct"] == -100.0 and c["closest_return_pct"] is None
    t = ov.track([a, b, c])
    assert t["skipped"] == 2 and t["skipped_wins"] == 1
    assert t["skipped_avg_return_pct"] == pytest.approx((a["closest_return_pct"] - 100.0) / 2, abs=0.1)


def test_the_closest_option_prefers_fewer_failed_checks():
    from tests.test_option_verdict import _chain, _close
    c = _close()
    spot = float(c.iloc[-1].round(-1))
    ch = _chain(spot, 0.5, 0.5, oi=50)                                   # every strike fails the OI check
    v = ov.assess(ch, c, None, [], "TEST", last_day="2026-11-04")
    assert v["verdict"] == "NO_TRADE" and v["closest"] is not None and v["plan"] is None
    cands = v["calls"] + v["puts"]
    assert len(v["closest"]["fails"]) == min(len(x["fails"]) for x in cands)


def test_session_refs_keep_the_last_sessions_unexpired_chains(monkeypatch):
    from scanner import options as opt
    monkeypatch.setattr(ov, "ist_today", lambda: date(2026, 11, 15))      # a Sunday scan
    monkeypatch.setattr(opt, "load_latest", lambda: {"chains": {
        "a": {"symbol": "NIFTY", "expiry": "2026-11-17", "day": "2026-11-13"},
        "b": {"symbol": "NIFTY", "expiry": "2026-11-23", "day": "2026-11-12"},       # an older session
        "c": {"symbol": "BANKNIFTY", "expiry": "2026-11-14", "day": "2026-11-13"}}})  # expired
    assert [r["symbol"] + r["expiry"] for r in ov._session_refs("2026-11-13")] == ["NIFTY2026-11-17"]


def test_the_scan_fetches_any_configured_index_chain_still_missing(monkeypatch):
    from scanner import options as opt
    calls = []
    monkeypatch.setattr(ov, "ist_today", lambda: date(2026, 11, 13))
    monkeypatch.setattr(ov.ol, "load", lambda: None)
    monkeypatch.setattr(opt, "load_latest", lambda: {"chains": {}})
    monkeypatch.setattr(opt, "refresh", lambda symbols=None, log=None, **k: calls.append(symbols) or {"chains": [], "errors": []})
    monkeypatch.setattr(ov, "load_config", lambda: {"options": {"underlyings": ["NIFTY", "FINNIFTY", "RELIANCE"]}})
    frames = {"close": pd.DataFrame({"NIFTY50": [25000.0]}, index=pd.to_datetime(["2026-11-13"]))}
    logs = []
    assert ov.record_stored_chains(frames, {}, log=logs.append) == 0
    assert calls == [["NIFTY", "FINNIFTY"]] and "fetched 0 missing index chain(s)" in logs[0]   # indices only
    calls.clear()
    assert ov.record_stored_chains(frames, {}, log=logs.append, fetch_missing=False) == 0 and calls == []


def test_the_plan_prices_from_the_premium_paid_even_when_the_model_disagrees():
    c = _fwd_chain()
    model = ov.premium_at(c, 25000.0, "ce", 30.0, 25000.0, 0.0)        # a 30% IV says about 2x what the market asks
    pick = {"strike": 25000.0, "side": "ce", "iv_pct": 30.0, "premium": round(model * 0.5, 2)}
    p = ov.plan(c, pick, {"stop_underlying": 24900.0, "target_underlying": 25300.0}, 65, 5)
    assert p["stop"] is not None and p["stop"] < p["entry"]          # the stop is there (it used to be dropped)
    assert p["target"] is None or p["target"] > p["entry"]           # 7 of 10 days of decay at 30% IV: maybe no gain
