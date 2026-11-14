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
