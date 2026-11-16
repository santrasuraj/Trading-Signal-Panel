"""Smart money: NSE's real file layouts and the insider source since May 2026 (scanner/smart_money.py). No network:
every refresh test replaces smart_money._fetch, every file goes to tmp_path."""
import json
from datetime import date

import pandas as pd

from scanner import smart_money as sm

TODAY = date(2026, 10, 28)
SHP = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
       'xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp/2025-06-30/in-bse-shp"')


def _cat(cid: str, member: str, pct: float) -> str:
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier></xbrli:entity>'
            '<xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period><xbrli:scenario>'
            '<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
            f'in-bse-shp:{member}</xbrldi:explicitMember></xbrli:scenario></xbrli:context>'
            f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{cid}">{pct}'
            '</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>')


def _holder(cid: str, axis: str, name: str, pct: float) -> str:
    """NSE's real layout: the name in 'D_<id>' (a duration), the shares and % in '<id>' (an instant)."""
    def ctx(i, period):
        return (f'<xbrli:context id="{i}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>'
                f'</xbrli:entity><xbrli:period>{period}</xbrli:period><xbrli:scenario>'
                f'<xbrldi:typedMember dimension="in-bse-shp:{axis}"><in-bse-shp:XDomain>{cid}</in-bse-shp:XDomain>'
                '</xbrldi:typedMember></xbrli:scenario></xbrli:context>')
    return (ctx(f"D_{cid}", "<xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate>")
            + ctx(cid, "<xbrli:instant>2026-09-30</xbrli:instant>")
            + f'<in-bse-shp:NameOfTheShareholder contextRef="D_{cid}">{name}</in-bse-shp:NameOfTheShareholder>'
            + f'<in-bse-shp:NumberOfShares contextRef="{cid}">{pct * 1e6:.0f}</in-bse-shp:NumberOfShares>'
            + f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{cid}">{pct / 100}'
              '</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>')


def real_shp() -> bytes:
    parts = [_cat("T", "ShareholdingPatternMember", 1.0), _cat("P", "ShareholdingOfPromoterAndPromoterGroupMember", 0.6),
             _cat("U", "PublicShareholdingMember", 0.4),
             _holder("OthersIndian_Context1", "DetailsOfSharesHeldByOthersIndianShareholdersAxis", "ABC HOLDINGS PVT LTD", 45),
             _holder("Individuals_Context1", "DetailsSharesHeldByIndividualsOrHUFAxis", "RAMESH KUMAR", 15),
             _holder("Insurance_Context1", "DetailsOfSharesHeldByInsuranceCompaniesAxis",
                     "LIFE INSURANCE CORPORATION OF INDIA", 1.9),
             _holder("Relatives_Context1", "DetailsOfSharesHeldByRelativesOfPromotersOtherThanPromoterGroupAxis",
                     "SURESH KUMAR", 2.0),
             _holder("Small_Context1", "DetailsOfSharesHeldByOtherNonInstitutionsAxis", "SMALL HOLDER", 0.4)]
    return f'<?xml version="1.0"?><xbrli:xbrl {SHP}>{"".join(parts)}</xbrli:xbrl>'.encode()


def test_holders_join_name_and_stake_and_use_the_promoter_table():
    cats, holders = sm.parse_shp_xbrl(real_shp())
    assert cats["promoter_pct"] == 60.0 and cats["public_pct"] == 40.0
    got = sorted((h["holder"], h["group"], h["pct"]) for h in holders)
    assert got == [("ABC HOLDINGS PVT LTD", "promoter", 45.0), ("LIFE INSURANCE CORPORATION OF INDIA", "public", 1.9),
                   ("RAMESH KUMAR", "promoter", 15.0), ("SURESH KUMAR", "public", 2.0)]   # public under 1% dropped


# ------------------------------------------------------------------ insider filings (corporates-pit-gg)
PIT = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" '
       'xmlns:in-bse-co="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-co"')


def pit_xbrl(person: str, txn: str, mode: str, qty: int, value: float, before: float, after: float,
             category: str = "Promoter Group") -> bytes:
    f = {"Symbol": "XYZ", "NameOfTheCompany": "XYZ LIMITED"}
    d = {"CategoryOfPerson": category, "NameOfThePerson": person, "TypeOfInstrument": "Equity",
         "SecuritiesAcquiredOrDisposedNumberOfSecurity": qty, "SecuritiesAcquiredOrDisposedValueOfSecurity": value,
         "SecuritiesAcquiredOrDisposedTransactionType": txn, "ModeOfAcquisitionOrDisposal": mode,
         "SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding": before,
         "SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding": after,
         "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate": "2026-10-20",
         "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate": "2026-10-21",
         "DateOfIntimationToCompany": "2026-10-22", "ExchangeOnWhichTheTradeWasExecuted": "NSE"}
    facts = "".join(f'<in-bse-co:{k} contextRef="MainI">{v}</in-bse-co:{k}>' for k, v in f.items())
    facts += "".join(f'<in-bse-co:{k} contextRef="Disclosure1">{v}</in-bse-co:{k}>' for k, v in d.items())
    return f'<?xml version="1.0"?><xbrli:xbrl {PIT}>{facts}</xbrli:xbrl>'.encode()


LISTING = json.dumps({"data": [
    {"appId": "11", "symbol": "XYZ", "companyName": "XYZ LIMITED", "broadcastDateTime": "22-Oct-2026 18:00:00",
     "typeOfSubmission": "Original", "prevAppId": None, "xmlFileName": "https://nsearchives.nseindia.com/IT_11.xml"},
    {"appId": "12", "symbol": "XYZ", "companyName": "XYZ LIMITED", "broadcastDateTime": "23-Oct-2026 18:00:00",
     "typeOfSubmission": "Original", "prevAppId": None, "xmlFileName": "https://nsearchives.nseindia.com/IT_12.xml"},
    {"appId": "13", "symbol": "OLD", "companyName": "OLD LIMITED", "broadcastDateTime": "02-May-2026 10:00:00",
     "typeOfSubmission": "Original", "prevAppId": None, "xmlFileName": "https://nsearchives.nseindia.com/IT_13.xml"},
    {"appId": "", "symbol": "BAD", "xmlFileName": None}]}).encode()


def test_insider_filing_xbrl_is_parsed_in_percent_units():
    rec = {"symbol": "XYZ", "company": "XYZ LIMITED", "broadcast": "2026-10-22T18:00:00+05:30", "xml": "u"}
    df = sm.parse_pit_xbrl(pit_xbrl("ABC HOLDINGS PVT LTD", "Sell", "Market Sale", 1000, 250000, 0.1394, 0.1384), rec)
    r = df.iloc[0]
    assert (r["side"], r["mode_kind"], r["before_pct"], r["after_pct"]) == ("SELL", "market", 13.94, 13.84)
    assert (r["disclosed"], r["trade_from"], r["exchange"], r["person_key"]) == (
        "2026-10-22", "2026-10-20", "NSE", "ABC HOLDINGS PRIVATE LIMITED")
    listing = sm.parse_pit_listing(LISTING)
    assert list(listing["app_id"]) == ["11", "12", "13"] and set(listing["status"]) == {"pending"}


def fake_nse(calls: list[str]):
    files = {"IT_11": pit_xbrl("ABC HOLDINGS PVT LTD", "Sell", "Market Sale", 1000, 250000, 0.14, 0.13),
             "IT_12": pit_xbrl("RAMESH KUMAR", "Buy", "Market Purchase", 500, 125000, 0.02, 0.03, "Director")}

    def fake(url, params=None, *, api=False, referer=None):
        calls.append(url)
        if url.endswith("corporates-pit-gg"):
            return 200, LISTING if (params or {}).get("from_date") == "01-10-2026" else b'{"data": []}'
        if url.endswith("corporates-pit"):
            return 200, b'{"acqNameList": [], "data": []}'     # what NSE answers since May 2026
        for k, body in files.items():
            if k in url:
                return 200, body
        return 404, b""
    return fake


def test_insider_refresh_reads_new_filings_once_and_skips_what_the_old_api_covered(tmp_path, monkeypatch):
    f = sm.files(tmp_path)
    # the old API already gave us OLD's filing of 2 May (same stock, same day): not downloaded again
    old = sm._frame([{"symbol": "OLD", "person": "X", "person_key": "X", "qty": 1.0, "disclosed": "2026-05-02",
                      "disclosed_at": "2026-05-02T10:00:00+05:30", "txn": "Buy"}], sm.INSIDER_COLS)
    sm._save_parquet(old, f["insider"])
    calls: list[str] = []
    monkeypatch.setattr(sm, "_fetch", fake_nse(calls))
    state = sm.load_state(tmp_path)
    res = sm._refresh_insider(tmp_path, state, TODAY, 200, lambda m: None, max_pit_xbrl=1)
    ins = sm.load_insider(tmp_path)
    assert res["status"] in ("ok", "partial") and len(ins) == 2       # OLD + the newest filing (cap 1)
    assert "1 insider filing left for the next refresh" in res["message"]
    filings = pd.read_parquet(f["pit_filings"]).set_index("app_id")["status"].to_dict()
    assert filings == {"11": "pending", "12": "ok", "13": "covered"}
    assert not any("IT_13" in c for c in calls)

    calls.clear()
    sm._refresh_insider(tmp_path, state, TODAY, 200, lambda m: None)
    ins = sm.load_insider(tmp_path)
    assert len(ins) == 3 and not any("IT_12" in c for c in calls)     # 12 is never read twice
    sell = ins[ins["person"] == "ABC HOLDINGS PVT LTD"].iloc[0]
    assert sell["role"] == "promoter" and sell["is_market"] and sell["side"] == "SELL"


# ------------------------------------------------------------------ who is who
def test_classifier_on_real_deal_names():
    c = sm.classify
    assert c("GQG PARTNERS INTERNATIONAL EQUITY CIT").category == "fii"
    assert c("RELIANCE TRUST INSTITUTIONAL RETIREMENT TRUST SERIES ELEVEN").category == "pension"
    assert c("RESILIENT ASSET MANAGEMENT B.V.").category == "fii"          # 'B.V.' becomes 'B V'
    assert c("PEAK XV PARTNERS INVESTMENTS VI-1").category == "aif"
    assert c("PI OPPORTUNITIES AIF V LLP").category == "aif"
    assert c("ARIHANT CAPITAL MARKETS LIMITED").category == "broker"
    assert c("ADANI INFRA (INDIA) LIMITED", company="Adani Ports and Special Economic Zone Ltd").category == "promoter"
    assert c("BAYER CROPSCIENCE AKTIENGESELLSCHAFT", company="Bayer CropScience Limited").category == "promoter"
    assert c("TATA ASSET MANAGEMENT LIMITED", company="Tata Motors Limited").category == "other"   # a fund house
    assert c("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", company="SBI Cards").category == "mf"
    assert "aif" in sm.BIG_MONEY and "aif" not in sm.INSTITUTIONS
