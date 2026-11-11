"""Market calendar, tax harvesting, options payoff and portfolio risk (web/api/services/calendar_svc.py, tax_svc.py,
payoff_svc.py, risk_svc.py). Synthetic data only: no NSE call, no real holdings."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scanner import events, options as opt
from scanner.costs import CostModel, TaxModel
from web.api.services import calendar_svc, payoff_svc, risk_svc, tax_svc

TAX = TaxModel()
CM = CostModel()


# ---- calendar ------------------------------------------------------------------------------------------------------
@pytest.fixture
def cal(monkeypatch):
    from web.api.services import data
    from scanner import watch
    monkeypatch.setattr(data, "universe", lambda: pd.DataFrame({"symbol": ["TCS", "INFY", "ITC"],
                                                                "company": ["TCS Ltd", "Infosys", "ITC Ltd"],
                                                                "industry": ["IT", "IT", "FMCG"]}))
    monkeypatch.setattr(data, "store", lambda: {"close": pd.DataFrame({"TCS": [4000.0], "ITC": [400.0]})})
    monkeypatch.setattr(data, "holdings_df", lambda: pd.DataFrame({"symbol": ["ITC"]}))
    monkeypatch.setattr(watch, "watchlists", lambda: {"lists": [{"name": "Main", "symbols": ["TCS"]}]})
    monkeypatch.setattr(events, "holiday_list", lambda y: [{"date": "2026-11-24", "name": "Guru Nanak Jayanti"}] if y == 2026 else [])
    monkeypatch.setattr(events, "board_meetings", lambda today, days: [
        {"symbol": "INFY", "date": "2026-11-20", "purpose": "Financial Results"},
        {"symbol": "ZZZ", "date": "2026-11-20", "purpose": "Financial Results"},          # not in the universe
        {"symbol": "TCS", "date": "2026-11-21", "purpose": "Fund Raising"}])
    ca = [{"symbol": "ITC", "series": "EQ", "subject": "Interim Dividend - Rs 8 Per Share", "exDate": "25-Nov-2026",
           "faceVal": "1"},
          {"symbol": "ITC", "series": "BE", "subject": "Interim Dividend - Rs 8 Per Share", "exDate": "25-Nov-2026",
           "faceVal": "1"},
          {"symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1", "exDate": "01-Dec-2026", "faceVal": "1"},
          {"symbol": "INFY", "series": "EQ", "subject": "Face Value Split (Sub-Division) - From Rs 10 To Rs 2",
           "exDate": "02-Dec-2026", "faceVal": "10"}]
    monkeypatch.setattr(calendar_svc, "_quarter_rows", lambda s, e: (ca, []))
    exps = {"NIFTY": [date(2026, 11, 17), date(2026, 11, 23), date(2026, 12, 29)],
            "BANKNIFTY": [date(2026, 11, 23), date(2026, 12, 29)], "RELIANCE": [date(2026, 11, 23)]}
    monkeypatch.setattr(opt, "expiries", lambda s: (exps.get(s, []), 200))


def test_calendar_merges_every_source_and_flags_your_stocks(cal):
    c = calendar_svc.calendar(30, today=date(2026, 11, 11))
    kinds = [(e["kind"], e.get("symbol")) for e in c["events"]]
    assert ("results", "INFY") in kinds and ("meeting", "TCS") in kinds and ("results", "ZZZ") not in kinds
    div = [e for e in c["events"] if e["kind"] == "dividend"]
    assert len(div) == 1                                                     # EQ and BE rows count once
    d = div[0]
    assert d["mine"] and d["amount"] == 8.0 and d["yield_pct"] == 2.0
    assert d["buy_by"] == "2026-11-23"                                       # the 24th is a holiday
    assert {e["kind"] for e in c["events"] if e.get("symbol") in ("TCS", "INFY")} >= {"bonus", "split"}
    tcs = next(e for e in c["events"] if e["kind"] == "bonus")
    assert tcs["watch"] and not tcs["mine"]
    exp = {e["date"]: e for e in c["events"] if e["kind"] == "expiry"}
    assert not exp["2026-11-17"]["monthly"] and exp["2026-11-23"]["monthly"]
    assert "Stock F&O" in exp["2026-11-23"]["detail"] and "2026-12-29" not in exp     # past the 30 days
    assert c["counts"]["holiday"] == 1 and c["notes"] == []


def test_calendar_notes_what_nse_did_not_send(cal, monkeypatch):
    def boom(*a):
        raise RuntimeError("NSE down")
    monkeypatch.setattr(events, "board_meetings", boom)
    monkeypatch.setattr(events, "holiday_list", lambda y: [])
    monkeypatch.setattr(opt, "expiries", lambda s: ([], 403))
    c = calendar_svc.calendar(30, today=date(2026, 11, 11))
    assert len(c["notes"]) == 3 and c["counts"]["dividend"] == 1


# ---- tax -----------------------------------------------------------------------------------------------------------
def test_tax_set_off_rules():
    t = tax_svc.tax_due(100_000, 200_000, TAX, 2026)
    assert t["tax"] == pytest.approx(100_000 * 0.208 + 75_000 * 0.13)
    t = tax_svc.tax_due(-50_000, 200_000, TAX, 2026)                    # a short-term loss eats long-term gains
    assert t["lt_net"] == 150_000 and t["tax"] == pytest.approx(25_000 * 0.13)
    t = tax_svc.tax_due(100_000, -80_000, TAX, 2026)                    # a long-term loss can't touch short-term gains
    assert t["st_net"] == 100_000 and t["carry_lt"] == 80_000 and t["tax"] == pytest.approx(20_800)
    assert tax_svc.tax_due(0, 0, TAX, 2023)["exempt"] == 100_000          # FY 2023-24: Rs 1 lakh


def test_long_term_dates_and_the_last_trade_day():
    assert tax_svc.long_term_from(date(2025, 11, 11)) == date(2025 + 1, 11, 12)
    assert tax_svc.long_term_from(date(2024, 2, 29)) == date(2025, 3, 1)
    assert tax_svc.fy_of(date(2027, 3, 31)) == 2026 and tax_svc.fy_of(date(2026, 4, 1)) == 2026
    assert tax_svc.trade_by(2026) == date(2027, 3, 30)                   # 31 Mar 2027 is a Wednesday
    assert tax_svc.trade_by(2026, {"2027-03-31"}) == date(2027, 3, 29)


def _holdings(rows):
    return pd.DataFrame(rows, columns=["symbol", "qty", "buy_price", "buy_date", "stop_loss_pct", "target_pct"])


def test_harvest_plan(monkeypatch):
    monkeypatch.setattr(tax_svc, "booked_from_fills", lambda fy: {"st": 0.0, "lt": 0.0, "trades": 0})
    today = date(2026, 11, 11)
    h = _holdings([["AAA", 1000, 100.0, date(2024, 1, 10), None, None],      # long term, +Rs 100 a share
                   ["BBB", 100, 500.0, date(2026, 6, 1), None, None],        # short term, -Rs 100 a share
                   ["CCC", 50, 200.0, date(2025, 12, 20), None, None],       # short term winner, long term on 21 Dec
                   ["OLD", 10, 50.0, date(2017, 5, 1), None, None]])         # grandfathered: left out
    prices = {"AAA": 200.0, "BBB": 400.0, "CCC": 260.0, "OLD": 500.0}
    p = tax_svc.plan(h, prices, today, 30_000.0, 25_000.0, TAX, CM)
    assert p["position"]["exempt_left"] == 100_000
    g = p["harvest_gains"]
    assert g["rows"][0]["symbol"] == "AAA" and g["rows"][0]["qty"] == 1000 and g["gain"] == 100_000
    assert g["tax_saved"] == pytest.approx(13_000) and g["worth_it"]
    loss = p["harvest_losses"]
    assert loss["rows"][0]["symbol"] == "BBB" and loss["rows"][0]["qty"] == 100   # needs the whole Rs 10,000 loss
    assert loss["tax_saved"] == pytest.approx(10_000 * 0.208)
    assert p["wait"][0]["symbol"] == "CCC" and p["wait"][0]["lt_from"] == "2026-12-21"
    assert any("1 Feb 2018" in n for n in p["notes"])
    lots = {x["symbol"]: x for x in p["lots"]}
    assert lots["AAA"]["term"] == "long" and lots["BBB"]["term"] == "short" and lots["OLD"]["grandfathered"]


def test_loss_harvest_sells_only_what_lowers_the_tax(monkeypatch):
    monkeypatch.setattr(tax_svc, "booked_from_fills", lambda fy: {"st": 0.0, "lt": 0.0, "trades": 0})
    h = _holdings([["BBB", 1000, 500.0, date(2026, 6, 1), None, None]])
    p = tax_svc.plan(h, {"BBB": 400.0}, date(2026, 11, 11), 5_000.0, 0.0, TAX, CM)
    assert p["harvest_losses"]["rows"][0]["qty"] == 50                    # Rs 5,000 of gains: 50 shares x Rs 100
    # two losers, Rs 50,000 of gains: each row's saving is its own, and they add up to the total
    h = _holdings([["ITC", 200, 470.0, date(2026, 5, 5), None, None], ["INF", 40, 1900.0, date(2026, 2, 10), None, None]])
    p = tax_svc.plan(h, {"ITC": 285.0, "INF": 1155.0}, date(2026, 11, 11), 50_000.0, 0.0, TAX, CM)
    rows = p["harvest_losses"]["rows"]
    assert [r["symbol"] for r in rows] == ["ITC", "INF"]
    assert rows[0]["tax_saved"] == pytest.approx(37_000 * 0.208) and rows[1]["qty"] == 18
    assert sum(r["tax_saved"] for r in rows) == pytest.approx(p["harvest_losses"]["tax_saved"])


# ---- payoff --------------------------------------------------------------------------------------------------------
def test_bull_call_spread_payoff():
    legs = [{"kind": "CE", "side": "buy", "strike": 100.0, "qty": 50, "price": 6.0, "iv": 0.2},
            {"kind": "CE", "side": "sell", "strike": 110.0, "qty": 50, "price": 2.0, "iv": 0.2}]
    r = payoff_svc.payoff(legs, spot=100.0, F=100.0, T=30 / 365, r=0.065, atm_iv=0.2)
    assert r["kind"] == "debit" and r["premium"] == -200
    assert r["max_profit"] == pytest.approx(300) and r["max_loss"] == pytest.approx(-200)
    assert r["breakevens"] == [pytest.approx(104.0, abs=0.01)]
    assert 0 < r["pop_pct"] < 60 and r["greeks"]["delta"] > 0 and r["reward_risk"] == 1.5


def test_naked_short_call_has_no_maximum_loss():
    legs = [{"kind": "CE", "side": "sell", "strike": 100.0, "qty": 10, "price": 3.0, "iv": 0.2}]
    r = payoff_svc.payoff(legs, spot=100.0, F=100.0, T=10 / 365, r=0.065, atm_iv=0.2)
    assert r["max_loss"] is None and r["max_profit"] == pytest.approx(30) and r["kind"] == "credit"
    assert r["greeks"]["theta"] > 0
    put = [{"kind": "PE", "side": "buy", "strike": 100.0, "qty": 10, "price": 3.0, "iv": 0.2}]
    r = payoff_svc.payoff(put, spot=100.0, F=100.0, T=10 / 365, r=0.065, atm_iv=0.2)
    assert r["max_profit"] == pytest.approx(970)                         # the price can only fall to zero


# ---- risk ----------------------------------------------------------------------------------------------------------
def test_portfolio_risk_numbers():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2023-01-02", periods=600)
    n = rng.normal(0, 0.01, len(idx))
    noise = rng.normal(0, 0.004, (len(idx), 2))
    rets = pd.DataFrame({"NIFTY50": n, "AAA": 2 * n + noise[:, 0], "BBB": 2 * n + noise[:, 1],
                         "CCC": rng.normal(0, 0.01, len(idx))}, index=idx)
    close = 100 * (1 + rets).cumprod()
    from scanner.providers import INDEX_NIFTY
    close = close.rename(columns={"NIFTY50": INDEX_NIFTY})
    h = _holdings([["AAA", 100, None, None, 10.0, None], ["BBB", 10, None, None, None, None],
                   ["CCC", 10, None, None, None, None]])
    prices = {"AAA": 100.0, "BBB": 100.0, "CCC": 100.0}
    out = risk_svc.analyse(h, prices, close, {"AAA": "IT", "BBB": "IT", "CCC": "FMCG"}, 8.0)
    pos = {p["symbol"]: p for p in out["positions"]}
    assert pos["AAA"]["beta"] == pytest.approx(2.0, abs=0.15) and abs(pos["CCC"]["beta"]) < 0.3
    assert out["at_risk"] == pytest.approx(100 * 10 + 10 * 8 + 10 * 8)       # stop % of the price without a buy price
    assert out["concentration"]["top_symbol"] == "AAA" and out["concentration"]["effective_n"] < 2
    assert out["risk"]["var99"] >= out["risk"]["var95"] > 0
    assert out["correlation"]["high_pairs"][0]["a"] in ("AAA", "BBB")
    assert out["shocks"][1]["nifty_pct"] == -10 and out["shocks"][1]["pct"] < -10
    assert any("AAA" in f for f in out["flags"])


def test_risk_without_holdings_says_so():
    out = risk_svc.analyse(_holdings([]), {}, pd.DataFrame(), {}, 8.0)
    assert out["empty"] and out["notes"]
