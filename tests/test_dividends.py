"""Dividends and rights issues (scanner/dividends.py) and how the backtest engine pays and taxes dividends
(scanner/engine.py). Synthetic data only: no NSE request is made (conftest switches the network off)."""
import numpy as np
import pandas as pd
import pytest

from scanner import dividends as dv
from scanner.costs import CostModel, TaxModel
from scanner.engine import RankStrategy, after_tax_equity, equal_weight_index, simulate
from scanner.panel import Factors, Panel


def test_dividend_texts_are_read_as_rupees_per_share():
    assert dv.dividend_amount("Interim Dividend - Rs 5 Per Share", 10) == 5
    assert dv.dividend_amount("Interim Dividend - Re 0.60 Per Share", 1) == 0.6
    assert dv.dividend_amount("Annual General Meeting / Dividend Rs - 20 Per Share", 10) == 20
    assert dv.dividend_amount("Interim Dividend - 14.50 Per Share", 10) == 14.5
    assert dv.dividend_amount("Final Dividend - Rs 5 Per Share And Special Dividend - Rs 3 Per Share", 10) == 8
    assert dv.dividend_amount("Dividend - 25%", 10) == 2.5                         # % of face value
    assert dv.dividend_amount("Dividend - 25%", None) is None
    assert dv.dividend_amount("Interim Dividend", 10) is None


def test_parse_keeps_equity_dividends_and_rights_once():
    rows = [
        {"symbol": "ABC", "series": "EQ", "exDate": "04-Nov-2026", "faceVal": "1", "subject": "Interim Dividend - Rs 5.75 Per Share"},
        {"symbol": "ABC", "series": "BE", "exDate": "04-Nov-2026", "faceVal": "1", "subject": "Interim Dividend - Rs 5.75 Per Share"},
        {"symbol": "ABC", "series": "EQ", "exDate": "04-Nov-2026", "faceVal": "1", "subject": "Interim Dividend - Rs 5.75 Per Share (Date Revised)"},
        {"symbol": "XYZ", "series": "EQ", "exDate": "05-Nov-2026", "faceVal": "10",
         "subject": "Interim Dividend- Rs 3 Per Share / Rights 1:16 @ Premium Rs 554 Per Share"},
        {"symbol": "SPL", "series": "EQ", "exDate": "05-Nov-2026", "faceVal": "10",
         "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"},
        {"symbol": "BND", "series": "N1", "exDate": "05-Nov-2026", "faceVal": "1000", "subject": "Interest Payment"},
    ]
    df, rep = dv.parse(rows)
    got = {(r.symbol, r.kind): r.amount for r in df.itertuples()}
    assert got[("ABC", "dividend")] == 5.75                                         # one dividend, not three
    assert got[("XYZ", "dividend")] == 3 and ("XYZ", "rights") in got
    assert ("SPL", "dividend") not in got and rep["dividend_unread"] == 0


def _acts(rows):
    df = pd.DataFrame(rows, columns=["symbol", "ex_date", "kind", "amount", "subject"])
    df["ex_date"] = pd.to_datetime(df["ex_date"])
    return df


def test_yield_is_on_the_raw_close_before_the_ex_date():
    idx = pd.bdate_range("2026-01-05", periods=5)
    adj = pd.DataFrame({"A": [20.0, 20, 20, 19.8, 19.8]}, index=idx)      # a later 1:5 split: adjusted = raw / 5
    raw = adj * 5
    acts = _acts([("A", idx[3], "dividend", 2.0, "Dividend - Rs 2 Per Share"),
                  ("A", pd.Timestamp("2026-01-10"), "dividend", 1.0, "on a Saturday: not a trading day")])
    y = dv.yields(adj, raw, acts)
    assert y.at[idx[3], "A"] == pytest.approx(2 / 100)                      # Rs 2 on the raw Rs 100, not the adjusted 20
    assert y.to_numpy().sum() == pytest.approx(0.02)


def test_total_return_index_accrues_the_dividend_yield():
    idx = pd.date_range("2025-01-01", periods=366, freq="D")
    price = pd.Series(100.0, index=idx)
    tr = dv.total_return(price, pd.Series(1.5, index=idx))
    assert tr.iloc[-1] / tr.iloc[0] == pytest.approx(1.015, abs=2e-4)      # 1.5% a year on a flat index
    assert dv.total_return(price, None) is price


def test_rights_terms_and_the_theoretical_ex_rights_price():
    assert dv.rights_terms("Rights 3:2 @ Premium Rs 62.50/-", 10) == (3, 2, 72.5)
    assert dv.rights_terms("Rights 87:38 @ Premium Of Rs 2.50 Per Share", 10) == (87, 38, 12.5)
    assert dv.rights_terms("Rights 1:1 @ Par", 10) == (1, 1, 10)
    assert dv.rights_terms("Rights 1:4 @ Rs 25 Per Share", 2) == (1, 4, 25)
    assert dv.rights_terms("Rights:14 Compulsory Convertible Debentures", 10) is None
    assert dv.rights_terms("Rights - 4:25 Fully Paid Up Shares @ Premium Rs 500/- Per Share / 2:25 Partly Paid Up Shares @ Premium Rs 605/-", 10) == (4, 25, 510)
    idx = pd.bdate_range("2019-03-25", periods=5)
    close = pd.DataFrame({"IDEA": [30.0, 29, 29, 17.6, 17.0], "S": [50.0, 50, 50, 25, 25], "HI": [10.0, 10, 10, 10, 10]}, index=idx)
    acts = _acts([("IDEA", idx[3], "rights", np.nan, "Rights 87:38 @ Premium Of Rs 2.50 Per Share"),
                  ("S", idx[3], "rights", np.nan, "with a split the same day"),
                  ("HI", idx[3], "rights", np.nan, "above the market")])
    acts["new"], acts["held"], acts["price"] = [87.0, 1, 1], [38.0, 1, 1], [12.5, 10, 20]
    out = dv.rights_factors(close, acts, skip={(idx[3], "S")})
    assert [a["symbol"] for a in out] == ["IDEA"]
    assert out[0]["factor"] == pytest.approx((38 + 87 * 12.5 / 29) / 125, abs=1e-6)   # TERP 17.5 on a close of 29


def _panel(closes: dict, divs: dict | None = None, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(next(iter(closes.values()))))
    c = pd.DataFrame(closes, index=idx, dtype=float)
    obs = pd.DataFrame(True, index=idx, columns=c.columns)
    d = None
    if divs:
        d = pd.DataFrame(0.0, index=idx, columns=c.columns)
        for (i, s), y in divs.items():
            d.iat[i, d.columns.get_loc(s)] = y
    return Panel(c, c * 1.01, c * 0.99, c, c * 0 + 1e6, pd.Series(100.0, index=idx), obs, None, d)


def test_engine_pays_dividends_on_held_stocks(monkeypatch):
    n = 300
    base = _panel({"A": [100.0] * n})
    with_div = _panel({"A": [100.0] * n}, {(270, "A"): 0.05})                 # 5% paid on day 270
    costs = CostModel(brokerage_pct=0, brokerage_max=0, stt_pct=0, exchange_pct=0, sebi_pct=0, stamp_buy_pct=0,
                      gst_pct=0, dp_per_sell=0, slippage_pct=0, slippage_illiquid_pct=0, cash_fee_pct=0)
    s = RankStrategy(key="hold", name="hold", description="", score=lambda f: f.p.close * 0 + 1.0, top_n=1,
                     keep_rank=1, rebalance="monthly", use_regime=False)
    trad = pd.DataFrame(True, index=base.dates, columns=base.symbols)
    r0 = simulate(s, Factors(base), costs, trad, capital=100_000, warmup=10)
    r1 = simulate(s, Factors(with_div), costs, trad, capital=100_000, warmup=10)
    assert r0.dividend_income == {}
    assert sum(r1.dividend_income.values()) == pytest.approx(5_000, rel=0.02)   # 5% of ~Rs 1 lakh held
    assert r1.equity.iloc[-1] - r0.equity.iloc[-1] == pytest.approx(sum(r1.dividend_income.values()), rel=1e-6)
    tax = TaxModel(interest_pct=30.0)
    fy = next(iter(r1.dividend_income))
    at0, at1 = after_tax_equity(r0, tax).iloc[-1], after_tax_equity(r1, tax).iloc[-1]
    paid = sum(r1.dividend_income.values())
    assert at1 - at0 == pytest.approx(paid * (0.7 if fy >= 2020 else 1.0), rel=0.02)
    ew0 = equal_weight_index(Factors(base), trad)
    ew1 = equal_weight_index(Factors(with_div), trad)
    assert ew1.iloc[-1] / ew0.iloc[-1] == pytest.approx(1.05, rel=1e-6)
