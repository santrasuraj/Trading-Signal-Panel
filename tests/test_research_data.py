"""The platform-style research data built from NSE's own files: the filings timeline (documents_svc), investor
portfolios from the shareholding filings (investors_svc), IV rank / percentile from the F&O bhavcopy (iv_history) and
our quality / value / momentum score (qvm). Synthetic inputs; nothing is fetched."""
import io
import math
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest


# ------------------------------------------------------------------ filings timeline
def test_announcements_go_on_the_right_shelf():
    from web.api.services.documents_svc import category
    assert category("Updates", "Infosys has informed the Exchange regarding 'Earnings Call Transcript'") == "transcript"
    assert category("Investor Presentation", "") == "presentation"
    assert category("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of analyst meet") == "call"
    assert category("Updates", "Audio recording of the earnings call") == "recording"
    assert category("Outcome of Board Meeting", "Financial Results for the quarter") == "results"
    assert category("Outcome of Board Meeting", "Appointment of director") == "board"
    assert category("Credit Rating", "") == "rating"
    assert category("Trading Window-XBRL", "closure of trading window") is None        # routine: left out


def test_documents_are_cached_sorted_and_linked(tmp_path, monkeypatch):
    from web.api.paths import P
    from web.api.services import documents_svc
    from scanner import events
    monkeypatch.setattr(P, "data", tmp_path)
    calls = []

    def get(path, params):
        calls.append(path)
        if path == "corporate-announcements":
            return [{"an_dt": "28-Oct-2026 17:38:42", "desc": "Updates", "attchmntText": "Earnings Call Transcript Q2",
                     "attchmntFile": "https://nsearchives.nseindia.in/corporate/T.pdf", "attFileSize": "300 KB"},
                    {"an_dt": "01-Feb-2025 10:00:00", "desc": "Trading Window", "attchmntText": "closure"},
                    {"an_dt": "17-Feb-2026 11:15:00", "desc": "Investor Presentation", "attchmntText": "AI day",
                     "attchmntFile": "javascript:alert(1)"}]
        return {"data": [{"fromYr": "2025", "toYr": "2026", "submission_type": "New", "disseminationDateTime": "29-MAY-2026 20:09:27",
                          "fileName": "https://nsearchives.nseindia.in/annual_reports/A.pdf"},
                         {"fromYr": "2025", "toYr": "2026", "submission_type": "Revised", "disseminationDateTime": "30-MAY-2026 20:04:14",
                          "fileName": "https://nsearchives.nseindia.in/annual_reports/B.pdf"}]}
    monkeypatch.setattr(events, "_get_json", get)
    d = documents_svc.documents("infy")
    assert [i["category"] for i in d["items"]] == ["transcript", "annual_report", "presentation"]
    assert d["items"][1]["url"].endswith("B.pdf")                    # the revised annual report wins
    assert d["items"][2]["url"] is None                               # never a non-https link
    n = len(calls)
    documents_svc.documents("INFY")
    assert len(calls) == n                                            # served from the cache
    with pytest.raises(Exception):
        documents_svc.documents("../../x")


# ------------------------------------------------------------------ investor portfolios
def test_investor_portfolios_add_up_accounts_and_show_quarter_changes(tmp_path, monkeypatch):
    from scanner import smart_money as sm
    from web.api.services import data, investors_svc as iv
    holders = pd.DataFrame([
        # SBI MF: two schemes in AAA both quarters (added), BBB only before (left / under 1%), CCC only now (new)
        ("AAA", "2026-06-30", "SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "public", 1e6, 1.0),
        ("AAA", "2026-06-30", "SBI MUTUAL FUND A/C SBI CONTRA FUND", "public", 1e6, 1.0),
        ("AAA", "2026-09-30", "SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "public", 1.5e6, 1.5),
        ("AAA", "2026-09-30", "SBI MUTUAL FUND A/C SBI CONTRA FUND", "public", 1e6, 1.0),
        ("BBB", "2026-06-30", "SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "public", 2e6, 1.2),
        ("CCC", "2026-09-30", "SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "public", 3e6, 2.0),
        ("AAA", "2026-09-30", "ASHISH KACHOLIA", "public", 5e5, 1.1),
        ("AAA", "2026-09-30", "PROMOTER PERSON", "promoter", 9e6, 50.0)],
        columns=["symbol", "period", "holder", "group", "shares", "pct"])
    holders["record_id"], holders["holder_key"], holders["xbrl_member"] = 1, holders["holder"], ""
    holdings = pd.DataFrame({"symbol": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"],
                             "period": ["2026-09-30", "2026-06-30"] * 3})
    holders.to_parquet(tmp_path / "holders.parquet")
    holdings.to_parquet(tmp_path / "holdings.parquet")
    monkeypatch.setattr(sm, "files", lambda folder=None: {"holders": tmp_path / "holders.parquet", "holdings": tmp_path / "holdings.parquet"})
    monkeypatch.setattr(data, "screener", lambda: pd.DataFrame({"symbol": ["AAA", "CCC"], "price": [100.0, 50.0]}))
    monkeypatch.setattr(data, "symbol_meta", lambda: {})
    iv._cache.clear()
    mf = iv.investors("mf")["rows"]
    assert len(mf) == 1 and mf[0]["investor"] == "SBI Mutual Fund"
    assert (mf[0]["stocks"], mf[0]["new"], mf[0]["added"], mf[0]["left"]) == (2, 1, 1, 1)
    assert mf[0]["value_cr"] == pytest.approx((2.5e6 * 100 + 3e6 * 50) / 1e7, abs=1)
    d = iv.investor(mf[0]["key"])
    by = {r["symbol"]: r for r in d["rows"]}
    assert by["AAA"]["pct"] == 2.5 and by["AAA"]["prev_pct"] == 2.0 and by["AAA"]["change"] == "added"
    assert len(by["AAA"]["accounts"]) == 2 and by["BBB"]["change"] == "left" and by["CCC"]["change"] == "new"
    famous = iv.investors("famous")["rows"]
    assert [r["investor"] for r in famous] == ["Ashish Kacholia"]
    assert all(r["investor"] != "Promoter Person" for r in iv.investors("all")["rows"])     # promoters are not here


# ------------------------------------------------------------------ IV rank
def _bhav(day: date, vol: float) -> bytes:
    """A tiny F&O bhavcopy: one index and one stock, ATM call and put priced at `vol` with Black-76."""
    from scanner.options import black76
    rows = []
    for sym, kind, spot, strikes, exp in (("NIFTY", "IDO", 25000.0, (24900.0, 25000.0, 25100.0), "2026-12-15"),
                                          ("INFY", "STO", 1141.5, (1120.0, 1140.0, 1160.0), "2026-12-29")):
        T = (pd.Timestamp(exp) - pd.Timestamp(day)).days / 365
        F = spot * math.exp(0.065 * T)
        for k in strikes:
            for typ in ("CE", "PE"):
                px = float(black76(F, k, T, 0.065, vol, 1.0 if typ == "CE" else 0.0))
                rows.append({"TradDt": day.isoformat(), "FinInstrmTp": kind, "TckrSymb": sym, "XpryDt": exp, "StrkPric": k,
                             "OptnTp": typ, "ClsPric": round(px, 2), "SttlmPric": round(px, 2), "OpnIntrst": 10,
                             "TtlTradgVol": 5, "UndrlygPric": spot, "NewBrdLotQty": 65})
        rows.append({"TradDt": day.isoformat(), "FinInstrmTp": kind, "TckrSymb": sym, "XpryDt": "2026-11-18", "StrkPric": spot,
                     "OptnTp": "CE", "ClsPric": 1.0, "SttlmPric": 1.0, "OpnIntrst": 1, "TtlTradgVol": 1,
                     "UndrlygPric": spot, "NewBrdLotQty": 65})                                # too near expiry: skipped
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fo.csv", pd.DataFrame(rows).to_csv(index=False))
    return buf.getvalue()


def test_daily_atm_iv_recovers_the_volatility_the_prices_were_made_with():
    from scanner import iv_history as ivh
    d = ivh.day_iv(_bhav(date(2026, 11, 13), 0.20), date(2026, 11, 13))
    by = d.set_index("symbol")
    assert by.loc["NIFTY", "iv"] == pytest.approx(20.0, abs=0.15) and by.loc["NIFTY", "strike"] == 25000.0
    assert by.loc["INFY", "iv"] == pytest.approx(20.0, abs=0.3) and by.loc["INFY", "strike"] == 1140.0
    assert by.loc["NIFTY", "dte"] == 32                                                       # not the 5-day expiry


def test_iv_rank_and_percentile_over_the_stored_year(tmp_path, monkeypatch):
    from scanner import fno, iv_history as ivh
    monkeypatch.setattr(fno, "folder", lambda: tmp_path)
    vols = [0.10, 0.20, 0.30, 0.15, 0.25]
    days = [date(2026, 11, 9) + pd.Timedelta(days=i) for i in range(5)]
    for d0, v in zip(days, vols):
        ivh.add_day(_bhav(d0, v), d0)
    t = ivh.ranks().set_index("symbol")
    assert t.loc["NIFTY", "iv"] == pytest.approx(25.0, abs=0.3)
    assert t.loc["NIFTY", "rank"] == pytest.approx(75.0, abs=2)                 # (25 - 10) / (30 - 10)
    assert t.loc["NIFTY", "percentile"] == pytest.approx(75.0)                   # 3 of the 4 earlier days were lower
    one = ivh.one("NIFTY")
    assert len(one["history"]) == 5 and one["days"] == 5
    ivh.add_day(_bhav(days[-1], 0.25), days[-1])                                 # the same day again: replaced
    assert len(ivh.load("NIFTY")) == 5


# ------------------------------------------------------------------ quality / value / momentum score
def test_score_ranks_quality_value_and_momentum_and_needs_all_three():
    from scanner import qvm
    rows = pd.DataFrame({"symbol": ["GOOD", "MID", "BAD", "BANK", "NODATA"],
                         "roe": [30.0, 15.0, 5.0, 16.0, None], "de": [0.1, 0.5, 2.0, None, 0.2],
                         "bank": [False, False, False, True, False], "earnings_yield": [6.0, 4.0, 2.0, 7.0, 5.0],
                         "book_yield": [0.3, 0.2, 0.1, 0.5, 0.2], "momentum_score": [2.0, 1.0, -1.0, 0.5, 1.5]})
    s = qvm.current(rows).set_index("symbol")
    assert s.loc["NODATA", "score"] is None                                      # no ROE: no score
    assert s.loc["GOOD", "score"] > s.loc["MID", "score"] > s.loc["BAD", "score"]
    assert s.loc["GOOD", "quality"] == 100.0 and s.loc["BAD", "quality"] == pytest.approx((25 + 100 / 3) / 2, abs=0.1)
    assert s.loc["BANK", "quality"] == 75.0                                       # banks: ROE alone (2nd of 4)


def test_score_frames_are_point_in_time_and_masked():
    from scanner import qvm
    dates = pd.bdate_range("2026-01-01", periods=3)
    cols = ["A", "B", "C"]
    f = lambda vals: pd.DataFrame([vals] * 3, index=dates, columns=cols)       # noqa: E731
    fin = {"roe": f([20.0, 10.0, np.nan]), "de": f([0.1, 1.0, 0.5]), "profit": f([10.0, 10.0, 10.0]),
           "equity": f([50.0, 100.0, 50.0]), "shares": f([1.0, 1.0, 1.0]), "bank": f([0.0, 0.0, 0.0])}
    close = f([100.0, 100.0, 100.0])
    mom = f([1.0, 2.0, 3.0])
    p = qvm.parts(close, mom, fin)
    assert p["score"]["C"].isna().all()                                           # no ROE that day
    assert p["quality"]["A"].iloc[0] == 100.0 and p["momentum"]["B"].iloc[0] == 100.0
    mask = f([True, False, True])
    assert qvm.parts(close, mom, fin, mask)["score"]["B"].isna().all()
