"""Ten-year financials (scanner/financials.py) and the company page (web/api/services/company_svc.py): both XBRL
layouts NSE serves (the integrated filing; the 2019-24 files whose columns are dated by facts, some never defined),
segments, NSE's pre-XBRL line items in lakh, ratios that respect gaps between years, the incremental update, and the
archive-domain fix for the quarterly numbers. Synthetic filings; nothing is fetched."""
import json
import math

import pandas as pd
import pytest

from scanner import financials as fin

CR = 1e7


def ctx(cid, start=None, end=None, instant=None, member=None):
    period = f"<xbrli:instant>{instant}</xbrli:instant>" if instant else \
        f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
    scen = (f'<xbrli:scenario><xbrldi:explicitMember dimension="in-capmkt:{member[0]}">in-capmkt:{member[1]}'
            f"</xbrldi:explicitMember></xbrli:scenario>") if member else ""
    return f'<xbrli:context id="{cid}"><xbrli:entity/><xbrli:period>{period}</xbrli:period>{scen}</xbrli:context>'


def fact(name, cid, v):
    return f'<in-capmkt:{name} contextRef="{cid}" unitRef="INR" decimals="-5">{v}</in-capmkt:{name}>'


def integrated_xbrl() -> str:
    """FY2026 integrated filing: the quarter, the year, the balance sheet, a cash flow and two segments."""
    parts = [ctx("Q", "2026-01-01", "2026-03-31"), ctx("Y", "2025-04-01", "2026-03-31"), ctx("I", instant="2026-03-31"),
             ctx("S1", "2025-04-01", "2026-03-31", member=("ReportableSegmentsAxis", "ReportableSegments1Member")),
             ctx("S2", "2025-04-01", "2026-03-31", member=("ReportableSegmentsAxis", "ReportableSegments2Member")),
             ctx("R1", "2025-04-01", "2026-03-31", member=("ReportableSegmentsFinanceCostsAxis", "ReportableSegments1Member"))]
    for cid, k in (("Q", 1), ("Y", 4)):
        parts += [fact("RevenueFromOperations", cid, 1000 * k * CR), fact("OtherIncome", cid, 20 * k * CR),
                  fact("Expenses", cid, 800 * k * CR), fact("DepreciationDepletionAndAmortisationExpense", cid, 50 * k * CR),
                  fact("FinanceCosts", cid, 30 * k * CR), fact("ProfitBeforeTax", cid, 220 * k * CR),
                  fact("CurrentTax", cid, 50 * k * CR), fact("DeferredTax", cid, 5 * k * CR),
                  fact("ProfitLossForPeriod", cid, 165 * k * CR), fact("ProfitOrLossAttributableToOwnersOfParent", cid, 160 * k * CR),
                  fact("BasicEarningsLossPerShare", cid, 16.0 * k)]
    parts += [fact("PaidUpValueOfEquityShareCapital", "Y", 100 * CR), fact("FaceValueOfEquityShareCapital", "Y", 10),
              fact("CashFlowsFromUsedInOperatingActivities", "Y", 700 * CR),
              fact("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "Y", -200 * CR),
              fact("DividendsPaidClassifiedAsFinancingActivities", "Y", -100 * CR),
              fact("EquityAttributableToOwnersOfParent", "I", 3000 * CR), fact("BorrowingsNoncurrent", "I", 600 * CR),
              fact("BorrowingsCurrent", "I", 400 * CR), fact("Assets", "I", 6000 * CR),
              fact("SegmentRevenue", "S1", 2500 * CR), fact("SegmentRevenue", "S2", 1500 * CR),
              fact("SegmentProfitLossBeforeTaxAndFinanceCosts", "R1", 500 * CR),
              '<in-capmkt:DescriptionOfReportableSegment contextRef="S1">Cement</in-capmkt:DescriptionOfReportableSegment>',
              '<in-capmkt:DescriptionOfReportableSegment contextRef="S2">Paints</in-capmkt:DescriptionOfReportableSegment>']
    return "<xbrli:xbrl>" + "".join(parts) + "</xbrli:xbrl>"


def old_format_xbrl() -> str:
    """A 2019-24 results file: both columns dated with the quarter; 'FourD' (the year) and 'OneI' never defined."""
    parts = [ctx("OneD", "2021-01-01", "2021-03-31"),
             '<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2021-01-01</in-bse-fin:DateOfStartOfReportingPeriod>',
             '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2021-03-31</in-bse-fin:DateOfEndOfReportingPeriod>',
             '<in-bse-fin:DateOfStartOfReportingPeriod contextRef="FourD">2020-04-01</in-bse-fin:DateOfStartOfReportingPeriod>',
             '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="FourD">2021-03-31</in-bse-fin:DateOfEndOfReportingPeriod>',
             fact("RevenueFromOperations", "OneD", 250 * CR), fact("RevenueFromOperations", "FourD", 900 * CR),
             fact("ProfitLossForPeriod", "OneD", 40 * CR), fact("ProfitLossForPeriod", "FourD", 150 * CR),
             fact("Equity", "OneI", 2000 * CR)]
    return "<xbrli:xbrl>" + "".join(parts) + "</xbrli:xbrl>"


def test_integrated_filing_year_quarter_balance_sheet_cash_flow_and_segments():
    y = fin.parse_xbrl(integrated_xbrl(), "2026-03-31", 12)
    q = fin.parse_xbrl(integrated_xbrl(), "2026-03-31", 3)
    assert y["revenue"] == 4000 * CR and q["revenue"] == 1000 * CR
    assert y["profit"] == 640 * CR                            # owners' share, not the group's 660
    assert y["tax"] == 220 * CR                               # current + deferred
    assert y["opex"] == (3200 - 200 - 120) * CR                # expenses less depreciation and interest
    assert y["equity"] == 3000 * CR and y["borrowings"] == 1000 * CR and y["total_assets"] == 6000 * CR
    assert y["capex"] == 200 * CR and y["dividends_paid"] == 100 * CR and y["cfo"] == 700 * CR
    assert [(s["name"], s["revenue"], s["result"]) for s in y["segments"]] == [("Cement", 2500 * CR, 500 * CR),
                                                                                ("Paints", 1500 * CR, None)]
    assert "segments" not in q                                # segment facts were only filed for the year


def test_2019_24_layout_columns_dated_by_facts_even_when_never_defined():
    y = fin.parse_xbrl(old_format_xbrl(), "2021-03-31", 12)
    q = fin.parse_xbrl(old_format_xbrl(), "2021-03-31", 3)
    assert (y["revenue"], y["profit"]) == (900 * CR, 150 * CR)
    assert (q["revenue"], q["profit"]) == (250 * CR, 40 * CR)
    assert y["equity"] == 2000 * CR                           # 'OneI': the balance sheet date


def test_pre_xbrl_line_items_are_lakh():
    d = {"resultsData2": {"re_net_sale": "5928900", "re_oth_tot_exp": "4341300", "re_depr_und_exp": "133100",
                          "re_pro_loss_bef_tax": "1893800", "re_tax": "512000", "re_net_profit": "1381800",
                          "re_bsc_eps_bfr_exi": "60.16", "re_pdup": "114800", "re_res_reval": "6686900",
                          "re_face_val": "5", "re_basic_eps": "0"}}
    o = fin.parse_old(d)
    assert o["revenue"] == pytest.approx(59289 * CR) and o["profit"] == pytest.approx(13818 * CR)
    assert o["equity"] == pytest.approx((1148 + 66869) * CR) and o["eps"] == 60.16 and o["face_value"] == 5
    assert o["opex"] == pytest.approx((43413 - 1331) * CR)


def rec_with(years: dict, quarters: dict | None = None, bank=False) -> dict:
    r = fin._blank("TEST")
    r["primary"], r["bank"] = "consolidated", bank
    r["bases"]["consolidated"]["years"] = years
    r["bases"]["consolidated"]["quarters"] = quarters or {}
    return r


def yr(rev, profit, equity=None, borrow=None, **kw):
    out = {"revenue": rev * CR, "opex": rev * 0.8 * CR, "pbt": profit * 1.3 * CR, "finance_costs": 10 * CR,
           "profit": profit * CR, "filed": "x", "id": "1", "src": "xbrl"}
    if equity is not None:
        out["equity"] = equity * CR
    if borrow is not None:
        out["borrowings"] = borrow * CR
    out.update(kw)
    return out


def test_ratios_and_growth_respect_gaps_between_years():
    years = {"2010-03-31": yr(100, 10, 50), "2011-03-31": yr(110, 11, 60),           # NSE lists nothing for 2012-15
             "2016-03-31": yr(200, 30, 150, 50), "2017-03-31": yr(220, 33, 170, 30),
             "2018-03-31": yr(242, 36.3, 190, 10), "2019-03-31": yr(266.2, 39.93, 210, 10)}
    t = fin.years_table(rec_with(years), "consolidated")
    assert math.isnan(t.loc[t["end"] == "2016-03-31", "sales_growth"].iloc[0])      # 2011 -> 2016 is not a year
    assert t.loc[t["end"] == "2017-03-31", "sales_growth"].iloc[0] == pytest.approx(10.0)
    r16 = t[t["end"] == "2016-03-31"].iloc[0]
    assert r16["roe"] == pytest.approx(30 / 150 * 100)        # no average with 2011's equity
    r17 = t[t["end"] == "2017-03-31"].iloc[0]
    assert r17["roce"] == pytest.approx((33 * 1.3 + 10) / ((150 + 50 + 170 + 30) / 2) * 100)
    g = fin.growth(t)
    assert g["sales_cagr_3y"] == pytest.approx(10.0, abs=0.01)                       # 2016 -> 2019
    assert g["sales_cagr_5y"] is None                                                # 2014 is not stored
    assert g["profit_cagr_10y"] is None


def test_banks_get_bank_ratios_not_roce_or_margins():
    years = {"2025-03-31": yr(300, 60, 400, 900, other_income=40 * CR), "2026-03-31": yr(330, 66, 440, 950, other_income=44 * CR)}
    t = fin.years_table(rec_with(years, bank=True), "consolidated")
    assert t["roce"].isna().all() and t["opm"].isna().all() and t["cash_conversion"].isna().all()
    assert t["nii"].iloc[-1] == pytest.approx(320 * CR) and t["cost_to_income"].notna().all()


def test_snapshot_values_the_company_from_its_shares_and_ttm_profit():
    years = {"2025-03-31": yr(400, 40, 300, 0, paid_up=100 * CR, face_value=10.0),
             "2026-03-31": yr(440, 44, 330, 0, paid_up=100 * CR, face_value=10.0)}
    qs = {e: yr(115, 12) for e in ("2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30")}
    s = fin.snapshot(rec_with(years, qs), price=500.0)
    assert s["shares"] == 1e8 and s["market_cap"] == 500e8                 # Rs 100 cr paid-up / Rs 10 face value
    assert s["pe"] == pytest.approx(500e8 / (48 * CR)) and s["pb"] == pytest.approx(500e8 / (330 * CR))
    assert s["profit_ttm"] == pytest.approx(48 * CR)


def test_update_is_incremental_and_keeps_bases_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(fin, "DIR", tmp_path)
    annual = [{"toDate": "31-Mar-2017", "fromDate": "01-Apr-2016", "consolidated": "Non-Consolidated", "filingDate": "21-Jun-2017 16:15",
               "xbrl": "https://nsearchives.nseindia.in/corporate/xbrl/-", "seqNumber": "111", "bank": "N", "params": "p", "format": "Old",
               "companyName": "Test Ltd"},
              {"toDate": "31-Mar-2021", "fromDate": "01-Apr-2020", "consolidated": "Consolidated", "filingDate": "14-Apr-2021 21:52",
               "xbrl": "https://nsearchives.nseindia.in/corporate/xbrl/OLD.xml", "seqNumber": "222", "bank": "N", "params": "q"}]
    integ = {"data": [{"type": "Integrated Filing- Financials", "qe_Date": "31-MAR-2026", "consolidated": "Consolidated",
                       "broadcast_Date": "23-Apr-2026 09:01:54", "xbrl": "https://nsearchives.nseindia.in/corporate/xbrl/INT.xml"}],
             "totalCount": 1}
    calls = {"json": 0, "bytes": []}

    def get(path, params):
        calls["json"] += 1
        if path == "corporates-financial-results":
            return annual if params["period"] == "Annual" else []
        if path == "integrated-filing-results":
            return integ
        if path == "corporates-financial-results-data":
            return {"resultsData2": {"re_net_sale": "1000", "re_net_profit": "100", "re_pdup": "10", "re_res_reval": "90"}}
        raise AssertionError(path)

    def get_bytes(url):
        calls["bytes"].append(url)
        return 200, (integrated_xbrl() if url.endswith("INT.xml") else old_format_xbrl()).encode()

    rec = fin.update("TEST", get=get, get_bytes=get_bytes, pause=0)
    assert sorted(rec["bases"]["consolidated"]["years"]) == ["2021-03-31", "2026-03-31"]
    assert sorted(rec["bases"]["standalone"]["years"]) == ["2017-03-31"]                       # never mixed
    assert rec["bases"]["standalone"]["years"]["2017-03-31"]["revenue"] == 1000 * fin.LAKH
    assert rec["bases"]["consolidated"]["years"]["2021-03-31"]["equity"] == 2000 * CR        # from the XBRL itself
    assert rec["bases"]["consolidated"]["quarters"]["2026-03-31"]["revenue"] == 1000 * CR    # same file, one download
    assert calls["bytes"].count("https://nsearchives.nseindia.in/corporate/xbrl/INT.xml") == 1
    assert rec["name"] == "Test Ltd" and rec["primary"] == "consolidated"
    before = len(calls["bytes"])
    fin.update("TEST", get=get, get_bytes=get_bytes, pause=0)
    assert len(calls["bytes"]) == before                                                       # nothing new: nothing fetched
    assert json.loads((tmp_path / "TEST.json").read_text())["checked"]


def test_point_in_time_frames_start_on_the_filing_day(tmp_path, monkeypatch):
    monkeypatch.setattr(fin, "DIR", tmp_path)
    r = rec_with({"2025-03-31": {**yr(100, 10, 80, 20), "filed": "2025-04-20"},
                  "2026-03-31": {**yr(110, 12, 90, 10), "filed": "2026-04-22"}})
    r["symbol"] = "AAA"
    fin._save("AAA", r)
    dates = pd.bdate_range("2025-04-01", "2026-06-30")
    f = fin.frames(["AAA"], dates)
    assert math.isnan(f["roe"].loc["2025-04-18", "AAA"]) and f["roe"].loc["2025-04-21", "AAA"] == pytest.approx(12.5)
    assert f["profit"].loc["2026-04-21", "AAA"] == 10 * CR and f["profit"].loc["2026-04-22", "AAA"] == 12 * CR


def test_quarterly_numbers_accept_nses_new_archive_domain():
    from scanner import fundamentals as fu
    rows = {"data": [{"type": "Integrated Filing- Financials", "qe_Date": "30-SEP-2026", "consolidated": "Consolidated",
                      "broadcast_Date": "23-Oct-2026 16:00:00", "xbrl": "https://nsearchives.nseindia.in/corporate/xbrl/A.xml"}],
            "totalCount": 1}
    out = fu.filings("AAA", get=lambda path, params: rows)
    assert [f["qe"] for f in out] == ["2026-09-30"]


def test_company_endpoint_serves_statements_peers_and_score(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from web.api.main import create_app
    from web.api.services import company_svc, data
    monkeypatch.setattr(fin, "DIR", tmp_path)
    r = rec_with({"2025-03-31": yr(400, 40, 300, 50, paid_up=100 * CR, face_value=10.0),
                  "2026-03-31": {**yr(440, 44, 330, 40, paid_up=100 * CR, face_value=10.0, cfo=50 * CR, capex=20 * CR,
                                     segments=[{"name": "Cement", "revenue": 300 * CR, "result": 60 * CR}]), "id": "https://x/a.xml"}})
    r["checked"] = pd.Timestamp.today().date().isoformat()
    fin._save("AAA", {**r, "symbol": "AAA"})
    monkeypatch.setattr(company_svc, "_price", lambda s: 500.0)
    monkeypatch.setattr(data, "symbol_meta", lambda: {"AAA": {"company": "Aaa Ltd", "industry": "Cement"}})
    monkeypatch.setattr(data, "screener", lambda: None)
    c = TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    d = c.get("/api/company/AAA").json()
    assert d["company"] == "Aaa Ltd" and d["years"]["periods"] == ["2025-03-31", "2026-03-31"]
    rev = next(x for x in d["years"]["rows"] if x["key"] == "revenue")
    assert rev["values"] == [400.0, 440.0] and d["years"]["sources"][-1]["url"] == "https://x/a.xml"
    assert d["cash_flow"]["periods"] == ["2026-03-31"] and d["segments"][0]["segments"][0]["name"] == "Cement"
    assert d["snapshot"]["market_cap"] == 5000.0 and d["peers"]["rows"][0]["symbol"] == "AAA"
    assert c.get("/api/company/../etc").status_code in (400, 404, 422)
