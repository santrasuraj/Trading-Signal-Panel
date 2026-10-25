"""Smart money (docs/smart_money_spec.md): NSE bulk/block, insider, FII/DII and shareholding parsers, the investor
classifier, the derived buyer / seller / exit tables, and refresh() end to end against a fake NSE (no network:
every refresh test replaces smart_money._fetch, every file goes to tmp_path)."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scanner import smart_money as sm
from scanner.lock import _try_lock, _unlock

# ------------------------------------------------------------------ NSE payloads (spec section 5, verbatim)
BULK_CSV = ("﻿Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
            '23-Oct-2026,ASTEC,Astec LifeSciences Ltd,HRTI PRIVATE LIMITED,BUY,"1,08,709",826.15,-\n'
            '23-Oct-2026,ASTEC,Astec LifeSciences Ltd,HRTI PRIVATE LIMITED,SELL,"1,05,000",827.40,-\n'
            '23-Oct-2026,ASTEC,Astec LifeSciences Ltd,SBI MUTUAL FUND A/C SBI SMALL CAP FUND,BUY,"2,50,000",820.00,-\n'
            "23-OCT-2026,XYZ,XYZ Limited,ASHISH RAMESHCHANDRA KACHOLIA,BUY,600000,412.35,-\n"
            "23-Oct-2026,XYZ,XYZ Limited,GOLDMAN SACHS (SINGAPORE) PTE,SELL,600000,412.10,-\n"
            "23-Oct-2026,PQR,PQR Ltd,SOME CLIENT,X,1000,10,-\n").encode("utf-8")
BLOCK_CSV = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
             "23-Oct-2026,OILCOUNTUB,Oil Country Tubular Ltd,UNITED STEEL ALLIED INDUSTRIES PVT LIMITED,SELL,4940000,65.3\n"
             "23-Oct-2026,OILCOUNTUB,Oil Country Tubular Ltd,NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND,BUY,4940000,65.3\n").encode()
BLOCK_EMPTY = b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
HIST_CSV = ('"Date","Symbol","Security Name","Client Name","Buy / Sell","Quantity Traded","Trade Price / Wght. Avg. Price","Remarks"\n'
            '"01-OCT-2026","ASTEC","Astec LifeSciences Ltd","SBI MUTUAL FUND A/C SBI SMALL CAP FUND","BUY","1,00,000","800.00","-"\n').encode()
HIST_JSON = b'{"data": [{"BD_DT_DATE": "01-OCT-2026", "BD_DT_ORDER": "2026-09-30T18:30:00.000+00:00", "BD_SYMBOL": "ASTEC", "BD_SCRIP_NAME": "Astec LifeSciences Ltd", "BD_CLIENT_NAME": "SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 100000, "BD_TP_WATP": 800.0, "BD_REMARKS": "-"}]}'
FIIDII_JSON = (b'[{"category": "DII **", "date": "23-Oct-2026", "buyValue": "15234.56", "sellValue": "12876.10", "netValue": "2358.46"},'
               b' {"category": "FII/FPI *", "date": "23-Oct-2026", "buyValue": "11000.00", "sellValue": "12888.42", "netValue": "-1888.42"}]')
PIT_JSON = json.dumps({"acqNameList": [], "data": [
    {"symbol": "XYZ", "company": "XYZ Limited", "anex": "7(2)", "acqName": "R K SHAH", "personCategory": "Promoter Group",
     "secType": "Equity Shares", "befAcqSharesNo": "1200000", "befAcqSharesPer": "12.00", "secAcq": "50,000",
     "secVal": "6250000", "tdpTransactionType": "Buy", "afterAcqSharesNo": "1250000", "afterAcqSharesPer": "12.50",
     "acqfromDt": "20-Oct-2026", "acqtoDt": "20-Oct-2026", "intimDt": "22-Oct-2026", "acqMode": "Market Purchase",
     "exchange": "NSE", "date": "22-Oct-2026 18:45", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/IT_1.xml"},
    {"symbol": "XYZ", "company": "XYZ Limited", "anex": "7(2)", "acqName": "R K SHAH", "personCategory": "Promoter Group",
     "secType": "Equity Shares", "befAcqSharesNo": "1200000", "befAcqSharesPer": "12.00", "secAcq": "50,000",
     "secVal": "6250000", "tdpTransactionType": "Buy", "afterAcqSharesNo": "1250000", "afterAcqSharesPer": "12.50",
     "acqfromDt": "20-Oct-2026", "acqtoDt": "20-Oct-2026", "intimDt": "22-Oct-2026", "acqMode": "Market Purchase",
     "exchange": "NSE", "date": "23-Oct-2026 10:00", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/IT_2.xml"},
    {"symbol": "XYZ", "company": "XYZ Limited", "acqName": "P DIRECTOR", "personCategory": "Director",
     "secType": "Equity Shares", "befAcqSharesNo": "10000", "befAcqSharesPer": "0.10", "secAcq": "10000",
     "secVal": "4100000", "tdpTransactionType": "Sell", "aftAcqSharesNo": "0", "aftAcqSharesPer": "0",
     "acqfromDt": "15-Oct-2026", "acqtoDt": "16-Oct-2026", "intimDt": "17-Oct-2026", "acqMode": "Market Sale",
     "exchange": "NSE", "date": "21-Oct-2026 19:02"},
    {"symbol": "ABC", "company": "ABC Ltd", "acqName": "ABC FAMILY TRUST", "personCategory": "Promoters",
     "secType": "Equity Shares", "befAcqSharesNo": "-", "befAcqSharesPer": "Nil", "secAcq": "25000", "secVal": "-",
     "tdpTransactionType": "Invocation", "acqMode": "Invocation of pledge", "acqfromDt": "18-Oct-2026",
     "acqtoDt": "18-Oct-2026", "intimDt": "20-Oct-2026", "exchange": "NSE", "date": "21-Oct-2026 11:30"},
    {"symbol": "ABC", "company": "ABC Ltd", "acqName": "S EMPLOYEE", "personCategory": "Designated Person",
     "secType": "Equity Shares", "secAcq": "500", "secVal": "50000", "tdpTransactionType": "Buy", "acqMode": "ESOP",
     "acqfromDt": "19-Oct-2026", "acqtoDt": "19-Oct-2026", "intimDt": "20-Oct-2026", "exchange": "NSE",
     "date": "21-Oct-2026 12:00"},
    {"symbol": "ABC", "company": "ABC Ltd", "acqName": "D TRADER", "personCategory": "Director", "secType": "Equity Shares",
     "secAcq": "-", "derivativeType": "Futures", "buyValue": "100000", "tdpTransactionType": "Buy", "acqMode": "Market Purchase",
     "date": "21-Oct-2026 12:30"}]}).encode()
SHP_MASTER_SEP = json.dumps([
    {"symbol": "XYZ", "name": "XYZ Limited", "date": "30-SEP-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_2001_15102026101010_WEB.xml",
     "revisedData": "N", "recordId": 2001, "pr_and_prgrp": 50.0, "public_val": 50.0, "submissionDate": "15-OCT-2026",
     "broadcastDate": "15-OCT-2026 10:10:10"},
    {"symbol": "XYZ", "name": "XYZ Limited", "date": "12-AUG-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1500_13082026101010_WEB.xml",
     "revisedData": "N", "recordId": 1500, "pr_and_prgrp": 51.0, "public_val": 49.0, "submissionDate": "13-AUG-2026",
     "broadcastDate": "13-AUG-2026 10:10:10"}]).encode()
SHP_MASTER_JUN = json.dumps({"data": [
    {"symbol": "XYZ", "name": "XYZ Limited", "date": "30-JUN-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1001_14072026090000_WEB.xml",
     "revisedData": "N", "recordId": 1001, "pr_and_prgrp": 52.0, "public_val": 48.0, "submissionDate": "14-JUL-2026",
     "broadcastDate": "14-JUL-2026 09:00:00"}]}).encode()
HIST_EMPTY = (b'"Date","Symbol","Security Name","Client Name","Buy / Sell","Quantity Traded",'
              b'"Trade Price / Wght. Avg. Price","Remarks"\n')

# ------------------------------------------------------------------ XBRL builder (spec section 5, verbatim)
NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp/2025-06-30/in-bse-shp"')


def _ctx(cid: str, member: str | None, typed: str | None = None) -> str:
    seg = ""
    if member:
        seg += ('<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
                f"in-bse-shp:{member}</xbrldi:explicitMember>")
    if typed:
        seg += (f'<xbrldi:typedMember dimension="in-bse-shp:{typed}Axis"><in-bse-shp:{typed}Domain>{cid}'
                f"</in-bse-shp:{typed}Domain></xbrldi:typedMember>")
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XYZ'
            f"</xbrli:identifier><xbrli:segment>{seg}</xbrli:segment></xbrli:entity><xbrli:period>"
            "<xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>")


def _facts(cid: str, shares: float, pct: float, name: str | None = None) -> str:
    out = (f'<in-bse-shp:NumberOfShares contextRef="{cid}" unitRef="shares" decimals="0">{shares:.0f}'
           "</in-bse-shp:NumberOfShares>"
           f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{cid}" unitRef="pure" '
           f'decimals="4">{pct}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>')
    if name:
        out += f'<in-bse-shp:NameOfTheShareholder contextRef="{cid}">{name}</in-bse-shp:NameOfTheShareholder>'
    return out


def make_xbrl(cats: dict[str, float], holders: list[tuple[str, str, str, float]], fraction: bool = True,
              total_shares: float = 10_000_000) -> bytes:
    """cats: category member -> percent; holders: (name, member, typed axis stem, percent). fraction=True writes
    0.5 for 50% (the scale NSE often uses)."""
    k = 0.01 if fraction else 1.0
    parts = []
    for i, (member, pct) in enumerate(cats.items()):
        parts.append(_ctx(f"C{i}", member) + _facts(f"C{i}", total_shares * pct / 100, round(pct * k, 6)))
    for j, (name, member, typed, pct) in enumerate(holders):
        parts.append(_ctx(f"H{j}", member, typed) + _facts(f"H{j}", total_shares * pct / 100, round(pct * k, 6), name))
    return f'<?xml version="1.0" encoding="UTF-8"?><xbrli:xbrl {NS}>{"".join(parts)}</xbrli:xbrl>'.encode()


CATS_SEP = {"ShareholdingPatternMember": 100.0, "ShareholdingOfPromoterAndPromoterGroupMember": 50.0,
            "PublicShareholdingMember": 50.0, "InstitutionsDomesticMember": 15.0, "InstitutionsForeignMember": 12.0,
            "MutualFundsMember": 10.0, "InsuranceCompaniesMember": 3.0, "BanksMember": 2.0}
HOLDERS_SEP = [("ABC HOLDINGS PRIVATE LIMITED", "ShareholdingOfPromoterAndPromoterGroupMember",
                "DetailsOfSharesHeldByPromoterAndPromoterGroup", 50.0),
               ("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "MutualFundsMember", "DetailsOfSharesHeldByMutualFunds", 6.0),
               ("GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA EQUITY PORTFOLIO", "ForeignPortfolioInvestorsCategoryIMember",
                "DetailsOfSharesHeldByForeignPortfolioInvestors", 1.2),
               ("CLEARING MEMBERS", "ClearingMembersMember", "DetailsOfSharesHeldByClearingMembers", 0.2),
               ("RANDOM INVESTOR", "IndividualsMember", "DetailsOfSharesHeldByIndividuals", 0.5),
               ("XYZ PAC", "ShareholdingOfPromoterAndPromoterGroupMember", "DetailsOfPersonsActingInConcert", 3.0)]
CATS_JUN = {"ShareholdingPatternMember": 100.0, "ShareholdingOfPromoterAndPromoterGroupMember": 52.0,
            "PublicShareholdingMember": 48.0, "InstitutionsDomesticMember": 12.0, "InstitutionsForeignMember": 13.5,
            "MutualFundsMember": 8.0, "InsuranceCompaniesMember": 3.0, "BanksMember": 1.0}
HOLDERS_JUN = [("ABC HOLDINGS PRIVATE LIMITED", "ShareholdingOfPromoterAndPromoterGroupMember",
                "DetailsOfSharesHeldByPromoterAndPromoterGroup", 52.0),
               ("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "MutualFundsMember", "DetailsOfSharesHeldByMutualFunds", 4.5),
               ("OLD VALUE FUND LTD", "BodiesCorporateMember", "DetailsOfSharesHeldByBodiesCorporate", 2.0)]

TODAY = date(2026, 10, 24)


def fake_nse(calls: list[str]):
    """A fake _fetch serving the payloads above; every requested URL is appended to `calls`."""
    def fake(url, params=None, *, api=False, referer=None):
        calls.append(url)
        p = params or {}
        if url == sm.BULK_CSV_URL:
            return 200, BULK_CSV
        if url == sm.BLOCK_CSV_URL:
            return 200, BLOCK_CSV
        if "historicalOR" in url:
            return 200, HIST_EMPTY
        if "corporates-pit" in url:
            return 200, PIT_JSON if p.get("from_date") == "01-10-2026" else b'{"data": []}'
        if "fiidiiTradeReact" in url:
            return 200, FIIDII_JSON
        if "corporate-share-holdings-master" in url:
            fd = p.get("from_date")
            return 200, SHP_MASTER_SEP if fd == "01-10-2026" else SHP_MASTER_JUN if fd == "01-07-2026" else b"[]"
        if "SHP_2001" in url:
            return 200, make_xbrl(CATS_SEP, HOLDERS_SEP)
        if "SHP_1001" in url:
            return 200, make_xbrl(CATS_JUN, HOLDERS_JUN)
        return 404, b""
    return fake


def _shp_store(folder):
    """Both quarters' parsed XBRL saved the way refresh() saves them, read back through the loaders."""
    hold, hol = [], []
    for rid, period, broadcast, cats, holders in (
            (2001, "2026-09-30", "2026-10-15T10:10:10+05:30", CATS_SEP, HOLDERS_SEP),
            (1001, "2026-06-30", "2026-07-14T09:00:00+05:30", CATS_JUN, HOLDERS_JUN)):
        c, hs = sm.parse_shp_xbrl(make_xbrl(cats, holders))
        hold.append({"symbol": "XYZ", "company": "XYZ Limited", "period": period, "record_id": rid,
                     "broadcast": broadcast, "source": "xbrl", **c})
        hol += [{"symbol": "XYZ", "period": period, "record_id": rid, "holder_key": sm.normalise_name(h["holder"]), **h}
                for h in hs]
    f = sm.files(folder)
    sm._save_parquet(sm._frame(hold, sm.HOLDING_COLS), f["holdings"])
    sm._save_parquet(sm._frame(hol, sm.HOLDER_COLS), f["holders"])
    return sm.load_holdings(folder), sm.load_holders(folder)


def _world(folder):
    holdings, holders = _shp_store(folder)
    insider = sm._enrich_insider(sm.parse_pit(PIT_JSON))
    net = sm.net_deals(sm.parse_deals(BULK_CSV, "bulk", "archive"), sm.promoter_sets(holders, insider),
                       sm.share_counts(holdings))
    ev = sm.events(net, insider, holdings, holders, "2026-10-01", companies=sm.company_names(net, insider, holdings))
    return net, insider, holdings, holders, ev


# ------------------------------------------------------------------ 1-3. names and classification
def test_normalise_and_parent_key():
    assert sm.parent_key("SBI MUTUAL FUND A/C SBI SMALL CAP FUND") == "SBI MUTUAL FUND"
    assert (sm.parent_key("NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND")
            == "NIPPON LIFE INDIA TRUSTEE LIMITED")
    assert sm.parent_key("SOCIETE GENERALE - ODI") == "SOCIETE GENERALE"
    assert sm.normalise_name("M/S ABC & Co. Pvt. Ltd.") == "ABC AND COMPANY PRIVATE LIMITED"
    assert sm.normalise_name("FUND-1").split() == ["FUND", "-", "1"]
    assert sm.normalise_name(None) == "" and sm.normalise_name(np.nan) == "" and sm.parent_key(None) == ""


NOT_INSURANCE = "not insurance"
CLASSIFY_CASES = [
    ("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", {}, ("mf", None, None)),
    ("NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND", {}, ("mf", None, None)),
    ("JIO BLACKROCK MUTUAL FUND", {}, ("mf", None, None)),
    ("BARODA BNP PARIBAS MUTUAL FUND A/C BARODA BNP PARIBAS LARGE CAP FUND", {}, ("mf", None, None)),
    ("LIC MUTUAL FUND", {}, ("mf", None, None)),
    ("ADITYA BIRLA SUN LIFE TRUSTEE PRIVATE LIMITED A/C ADITYA BIRLA SUN LIFE FLEXI CAP FUND", {}, ("mf", None, None)),
    ("LIFE INSURANCE CORPORATION OF INDIA", {}, ("insurance", None, None)),
    ("HDFC LIFE INSURANCE COMPANY LIMITED", {}, ("insurance", None, None)),
    ("TATA AIA LIFE INSURANCE COMPANY LIMITED", {}, ("insurance", None, None)),
    ("LIC HOUSING FINANCE LIMITED", {}, ("bank", None, None)),
    ("NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL", {}, ("pension", None, None)),
    ("GOVERNMENT OF SINGAPORE", {}, ("pension", None, None)),
    ("ABU DHABI INVESTMENT AUTHORITY", {}, ("pension", None, None)),
    ("GIC PRIVATE LIMITED", {}, ("pension", None, None)),
    ("GRAVITON RESEARCH CAPITAL LLP", {}, ("broker", None, None)),
    ("HRTI PRIVATE LIMITED", {}, ("broker", None, None)),
    ("BNP PARIBAS ARBITRAGE", {}, ("broker", None, None)),
    ("SOCIETE GENERALE - ODI", {}, ("fii", sm.ODI_LABEL, None)),
    ("MORGAN STANLEY ASIA (SINGAPORE) PTE.", {}, ("fii", sm.ODI_LABEL, None)),
    ("GOLDMAN SACHS (SINGAPORE) PTE", {}, ("fii", sm.ODI_LABEL, None)),
    ("HDFC BANK LIMITED", {}, ("bank", None, None)),
    ("BAJAJ FINANCE LIMITED", {}, ("bank", None, None)),
    ("KOTAK MAHINDRA BANK LIMITED", {}, ("bank", None, None)),
    ("VANGUARD EMERGING MARKETS STOCK INDEX FUND", {}, ("fii", None, None)),
    ("ISHARES CORE MSCI EMERGING MARKETS ETF", {}, ("fii", None, None)),
    ("SMALLCAP WORLD FUND, INC", {}, ("fii", None, None)),
    ("COPTHALL MAURITIUS INVESTMENT LIMITED", {}, ("fii", None, None)),
    ("GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA EQUITY PORTFOLIO", {}, ("fii", None, None)),
    ("ASHISH RAMESHCHANDRA KACHOLIA", {}, ("famous", None, "Ashish Kacholia")),
    ("REKHA RAKESH JHUNJHUNWALA", {}, ("famous", None, "Rekha Jhunjhunwala (RJ estate)")),
    ("ABAKKUS EMERGING OPPORTUNITIES FUND-1", {}, ("famous", None, "Sunil Singhania (Abakkus)")),
    ("RAJESH KUMAR", {}, ("other", "Individual", None)),
    ("ABC ENTERPRISES PRIVATE LIMITED", {}, ("other", "Company", None)),
    ("RAMESH HUF", {}, ("other", "HUF/Trust", None)),
    ("CLICK COMMERCE LLP", {}, NOT_INSURANCE),
    ("PUBLICIS GROUPE", {}, NOT_INSURANCE),
    ("XYZ TRADERS PRIVATE LIMITED", {"round_trip": True}, ("broker", None, None)),
    ("ABC HOLDINGS PRIVATE LIMITED", {"promoters": {"ABC HOLDINGS PRIVATE LIMITED"}}, ("promoter", None, None)),
    ("ASTEC HOLDINGS PRIVATE LIMITED", {"company": "Astec LifeSciences Ltd"}, ("promoter", sm.LIKELY_PROMOTER, None)),
    ("", {}, ("other", "Unclassified", None)),
]


@pytest.mark.parametrize("name, kwargs, expected", CLASSIFY_CASES)
def test_classify_table(name, kwargs, expected):
    label = sm.classify(name, **kwargs)
    if expected == NOT_INSURANCE:
        assert label.category != "insurance"
    else:
        assert tuple(label) == expected


def test_famous_aliases_need_two_tokens():
    for tokens, _ in sm._ALIASES:
        assert len(tokens) >= 2 or tokens <= sm.BRAND_TOKENS
    assert sm.classify("ASHISH SHAH").category != "famous"


# ------------------------------------------------------------------ 4-10. parsers
def test_parse_bulk_and_block():
    assert BULK_CSV.startswith(chr(0xFEFF).encode("utf-8"))   # the file starts with a byte-order mark
    bulk = sm.parse_deals(BULK_CSV, "bulk", "archive")
    assert len(bulk) == 5 and list(bulk.columns) == list(sm.DEAL_COLS)
    assert set(bulk["date"]) == {"2026-10-23"}
    assert "PQR" not in set(bulk["symbol"])                  # side 'X' is dropped, never defaulted to BUY
    hrti = bulk[(bulk["client"] == "HRTI PRIVATE LIMITED") & (bulk["side"] == "BUY")]
    assert len(hrti) == 1 and hrti.iloc[0]["qty"] == 108709.0
    assert np.allclose(bulk["value"], bulk["qty"] * bulk["price"])
    assert bulk["remarks"].isna().all() and set(bulk["source"]) == {"archive"}
    empty = sm.parse_deals(BLOCK_EMPTY, "block", "archive")
    assert empty.empty and list(empty.columns) == list(sm.DEAL_COLS)
    block = sm.parse_deals(BLOCK_CSV, "block", "archive")
    assert len(block) == 2 and set(block["kind"]) == {"block"}


def test_parse_history_csv_and_json():
    a = sm.parse_deals(HIST_CSV, "bulk", "history")
    b = sm.parse_deals(HIST_JSON, "bulk", "history")
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 1
    r = a.iloc[0]
    assert r["date"] == "2026-10-01" and r["qty"] == 100000 and r["price"] == 800 and r["side"] == "BUY"


def test_net_deals_round_trip_and_counterparties():
    deals = pd.concat([sm.parse_deals(BULK_CSV, "bulk", "archive"), sm.parse_deals(BLOCK_CSV, "block", "archive")],
                      ignore_index=True)
    net = sm.net_deals(deals, shares={"XYZ": 10_000_000})
    assert list(net.columns) == list(sm.NET_DEAL_COLS)
    by = net.set_index("client_key")
    hrti = by.loc["HRTI PRIVATE LIMITED"]
    assert hrti["round_trip"] and hrti["side"] == "BUY" and hrti["net_qty"] == 3709 and hrti["category"] == "broker"
    sbi = by.loc["SBI MUTUAL FUND"]
    assert sbi["category"] == "mf" and sbi["net_value"] == pytest.approx(205_000_000) and pd.isna(sbi["pct_equity"])
    kach = by.loc["ASHISH RAMESHCHANDRA KACHOLIA"]
    assert kach["category"] == "famous" and kach["investor"] == "Ashish Kacholia"
    assert kach["pct_equity"] == pytest.approx(6.0)
    gs = by.loc["GOLDMAN SACHS SINGAPORE PTE"]
    assert gs["category"] == "fii" and gs["sub_label"] == sm.ODI_LABEL and gs["side"] == "SELL"
    nip = by.loc["NIPPON LIFE INDIA TRUSTEE LIMITED"]
    assert nip["kind"] == "block" and nip["side"] == "BUY" and nip["category"] == "mf"
    assert nip["counterparties"] == ["UNITED STEEL ALLIED INDUSTRIES PVT LIMITED"]
    assert kach["counterparties"] == []
    assert net["date"].iloc[0] == "2026-10-23" and net.iloc[0]["client_key"] == "NIPPON LIFE INDIA TRUSTEE LIMITED"


def test_parse_pit():
    raw = sm.parse_pit(PIT_JSON)
    assert len(raw) == 4 and list(raw.columns) == list(sm.INSIDER_COLS)   # derivative row and revised copy gone
    shah = raw[raw["person"] == "R K SHAH"]
    assert len(shah) == 1 and shah.iloc[0]["disclosed"] == "2026-10-23"
    ins = sm._enrich_insider(raw)
    assert list(ins.columns) == list({**sm.INSIDER_COLS, **sm.INSIDER_EXTRA_COLS})
    by = ins.set_index("person")
    s = by.loc["R K SHAH"]
    assert s["role"] == "promoter" and s["category"] == "promoter" and s["is_market"]
    assert s["change_pts"] == pytest.approx(0.5) and s["avg_price"] == pytest.approx(125.0)
    assert s["id"] == "XYZ|R K SHAH|2026-10-20|50000|BUY"
    d = by.loc["P DIRECTOR"]
    assert d["fully_exited"] and d["delay_days"] == 5 and d["after_shares"] == 0
    assert d["category"] == "other" and d["sub_label"] == sm.INSIDER_LABEL
    p = by.loc["ABC FAMILY TRUST"]
    assert p["mode_kind"] == "pledge_invoked" and pd.isna(p["side"]) and pd.isna(p["value"]) and not p["is_market"]
    e = by.loc["S EMPLOYEE"]
    assert e["mode_kind"] == "esop" and not e["is_market"]


def test_parse_fiidii():
    df = sm.parse_fiidii(FIIDII_JSON)
    assert len(df) == 1 and list(df.columns) == list(sm.FLOW_COLS)
    r = df.iloc[0]
    assert r["date"] == "2026-10-23"
    assert r["fii_net_cr"] == pytest.approx(-1888.42) and r["dii_net_cr"] == pytest.approx(2358.46)
    assert r["dii_buy_cr"] == pytest.approx(15234.56)


def test_parse_shp_master():
    df = sm.parse_shp_master(SHP_MASTER_SEP)
    assert len(df) == 1 and list(df.columns) == list(sm.FILING_COLS)   # the 12-Aug allotment pattern is dropped
    r = df.iloc[0]
    assert r["record_id"] == 2001 and r["period"] == "2026-09-30"
    assert r["broadcast"] == "2026-10-15T10:10:10+05:30" and not r["revised"]
    assert len(sm.parse_shp_master(SHP_MASTER_JUN)) == 1


def test_parse_shp_xbrl_both_scales():
    cats, holders = sm.parse_shp_xbrl(make_xbrl(CATS_SEP, HOLDERS_SEP))
    cats2, holders2 = sm.parse_shp_xbrl(make_xbrl(CATS_SEP, HOLDERS_SEP, fraction=False))
    assert cats == cats2 and holders == holders2
    assert cats == {"total_shares": 10_000_000, "promoter_pct": 50, "public_pct": 50, "fii_pct": 12, "dii_pct": 15,
                    "mf_pct": 10, "insurance_pct": 3, "banks_pct": 2, "pension_pct": 0.0, "aif_pct": 0.0}
    got = sorted((h["holder"], h["group"], h["pct"]) for h in holders)
    assert got == sorted([("ABC HOLDINGS PRIVATE LIMITED", "promoter", 50.0),
                          ("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "public", 6.0),
                          ("GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA EQUITY PORTFOLIO", "public", 1.2)])
    with pytest.raises(ValueError):
        sm.parse_shp_xbrl(make_xbrl({}, []))


def test_non_promoter_non_public_holder_is_not_a_promoter():
    # an employee trust is filed under "Non Promoter - Non Public": the word "promoter" in it must not make it one
    cats = {"ShareholdingPatternMember": 100.0, "ShareholdingOfPromoterAndPromoterGroupMember": 60.0,
            "PublicShareholdingMember": 38.0, "NonPromoterNonPublicShareholdingMember": 2.0}
    trust = ("XYZ EMPLOYEE WELFARE TRUST", "NonPromoterNonPublicShareholdingMember",
             "DetailsOfSharesHeldByEmployeeBenefitTrust", 2.0)
    cats_out, holders = sm.parse_shp_xbrl(make_xbrl(cats, [trust]))
    assert [(h["holder"], h["group"]) for h in holders] == [("XYZ EMPLOYEE WELFARE TRUST", "public")]
    assert cats_out["promoter_pct"] == 60.0 and cats_out["public_pct"] == 38.0


# ------------------------------------------------------------------ 11-12. events, exits and stock signals
def test_events_and_exits(tmp_path):
    net, insider, holdings, holders, ev = _world(tmp_path)
    assert list(ev.columns) == list(sm.EVENT_COLS)
    xyz = ev[ev["symbol"] == "XYZ"]
    shp = {(r["event"], r["who_key"]): r for r in xyz[xyz["source"] == "shareholding"].to_dict("records")}
    assert set(shp) == {("category_up", "mf"), ("category_up", "bank"), ("category_down", "fii"),
                        ("category_down", "promoter"), ("holder_cut", "ABC HOLDINGS PRIVATE LIMITED"),
                        ("holder_added", "SBI MUTUAL FUND A/C SBI SMALL CAP FUND"),
                        ("new_holder", "GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA EQUITY PORTFOLIO"),
                        ("holder_dropped", "OLD VALUE FUND LIMITED")}
    assert shp[("category_up", "mf")]["change_pts"] == pytest.approx(2.0)
    assert shp[("category_up", "bank")]["change_pts"] == pytest.approx(1.0)
    assert shp[("category_down", "fii")]["change_pts"] == pytest.approx(-1.5)
    assert shp[("category_down", "promoter")]["change_pts"] == pytest.approx(-2.0)
    assert shp[("holder_added", "SBI MUTUAL FUND A/C SBI SMALL CAP FUND")]["change_pts"] == pytest.approx(1.5)
    dropped = shp[("holder_dropped", "OLD VALUE FUND LIMITED")]
    assert dropped["exit_kind"] == "below_1pct" and "sold some or all" in dropped["text"]
    assert all(r["date"] == "2026-10-15" and r["period"] == "2026-09-30" for r in shp.values())
    assert shp[("category_down", "promoter")]["text"] == "Promoter holding fell −2.00 pts to 50.00% (quarter to Sep 2026)"

    ins = {(r["event"], r["who"]): r for r in ev[ev["source"] == "insider"].to_dict("records")}
    assert ins[("insider_exit", "P DIRECTOR")]["exit_kind"] == "full_exit"
    assert ins[("insider_exit", "P DIRECTOR")]["text"] == (
        "Insider P DIRECTOR sold all their shares (10,000 shares, ₹41.0 lakh) - fully exited")
    assert ins[("insider_buy", "R K SHAH")]["weight"] == 2
    assert ("pledge_invoked", "ABC FAMILY TRUST") in ins
    assert not any(who == "S EMPLOYEE" for _, who in ins)

    deals = ev[ev["source"].isin(["bulk", "block"])]
    gs = deals[deals["who"] == "GOLDMAN SACHS (SINGAPORE) PTE"]
    assert len(gs) == 1 and gs.iloc[0]["event"] == "deal_sell" and gs.iloc[0]["exit_kind"] == "sold_part"
    assert gs.iloc[0]["text"] == ("GOLDMAN SACHS (SINGAPORE) PTE sold 6,00,000 shares (₹24.7 cr, 6.00% of the "
                                  "company) in a bulk deal")
    assert not (deals["who"] == "HRTI PRIVATE LIMITED").any()   # intraday round trip: no event
    assert ev["id"].is_unique


def test_stock_signals_and_lists(tmp_path):
    net, insider, holdings, holders, ev = _world(tmp_path)
    sig = sm.stock_signals(ev, net, holdings, "2026-10-01")
    assert list(sig.columns) == list(sm.SIGNAL_COLS)
    xyz = sig[sig["symbol"] == "XYZ"].iloc[0]
    assert xyz["inst_sellers"] == 1 and xyz["famous_buyers"] == ["Ashish Kacholia"]
    assert xyz["promoter_buying"] and xyz["mf_chg_pts"] == pytest.approx(2.0) and xyz["exits"] >= 2
    assert xyz["direction"] == "mixed" and xyz["period"] == "2026-09-30" and len(xyz["reasons"]) == 4
    abc = sig[sig["symbol"] == "ABC"].iloc[0]
    assert abc["pledge_invoked"] and abc["direction"] == "down"
    assert "XYZ" in set(sm.accumulating(sig)["symbol"]) and "XYZ" in set(sm.exiting(sig)["symbol"])
    top = sm.top_reasons(ev[ev["symbol"] == "XYZ"], "down", 2)
    assert len(top) == 2 and top[0].startswith("GOLDMAN SACHS (SINGAPORE) PTE sold")


def test_loaders_and_derived_on_an_empty_folder(tmp_path):
    assert list(sm.load_deals(tmp_path).columns) == list(sm.DEAL_COLS)
    assert list(sm.load_insider(tmp_path).columns) == list({**sm.INSIDER_COLS, **sm.INSIDER_EXTRA_COLS})
    assert list(sm.load_flows(tmp_path).columns) == list(sm.FLOW_COLS)
    assert list(sm.load_holdings(tmp_path).columns) == list(sm.HOLDING_COLS)
    assert list(sm.load_holders(tmp_path).columns) == list({**sm.HOLDER_COLS, **sm.HOLDER_EXTRA_COLS})
    assert sm.load_state(tmp_path)["deals_months_done"] == {"bulk": [], "block": []}
    net = sm.net_deals(sm.load_deals(tmp_path))
    ev = sm.events(net, sm.load_insider(tmp_path), sm.load_holdings(tmp_path), sm.load_holders(tmp_path), None)
    assert net.empty and ev.empty and list(ev.columns) == list(sm.EVENT_COLS)
    assert sm.stock_signals(ev, net, sm.load_holdings(tmp_path), None).empty
    assert sm.holder_changes(sm.load_holders(tmp_path), sm.load_holdings(tmp_path)).empty
    assert sm.summary_lines(tmp_path) == [] and not sm.refresh_running(tmp_path)
    assert sm.window("2026-10-23", 1) == "2026-10-23" and sm.window("2026-10-23", 30) == "2026-09-24"
    assert sm.window(None, 30) is None and sm.latest(net, "date") is None


# ------------------------------------------------------------------ 13-15. refresh
def test_refresh_end_to_end(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sm, "_fetch", fake_nse(calls))
    kw = dict(days=60, log=lambda m: None, symbols=["XYZ"], folder=tmp_path, today=TODAY)
    rep = sm.refresh(**kw)
    assert rep["ok"], rep
    assert {n: s["status"] for n, s in rep["sources"].items()} == {
        "deals": "ok", "insider": "ok", "flows": "ok", "holdings": "ok"}
    assert len(sm.load_deals(tmp_path)) == 7
    assert len(sm.load_insider(tmp_path)) == 4
    assert len(sm.load_flows(tmp_path)) == 1
    holdings = sm.load_holdings(tmp_path)
    assert len(holdings) == 2 and set(holdings["source"]) == {"xbrl"}
    assert len(sm.load_holders(tmp_path)) == 6
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "xbrl" / "SHP_2001.xml.gz").exists() and (tmp_path / "xbrl" / "SHP_1001.xml.gz").exists()
    state = sm.load_state(tmp_path)
    assert "2026-09" in state["deals_months_done"]["bulk"] and "2026-10" not in state["insider_months_done"]
    assert state["last_run"]["ok"] and state["sources"]["deals"]["latest_date"] == "2026-10-23"
    lines = sm.summary_lines(tmp_path)
    assert lines[0] == "Smart money - NSE disclosures (deals of 23 Oct 2026):"
    assert lines[-1] == "Disclosed data, not a tip: big investors also lose money."
    assert any(x.startswith("FII/FPI net −1,888 cr, DII net +2,358 cr") for x in lines)

    n = len(calls)
    rep2 = sm.refresh(**kw)
    assert rep2["ok"], rep2
    assert rep2["sources"]["deals"]["rows_added"] == 0 and rep2["sources"]["insider"]["rows_added"] == 0
    assert not any("SHP_" in u for u in calls[n:])   # parsed filings are never downloaded again
    assert len(sm.load_deals(tmp_path)) == 7 and len(sm.load_holdings(tmp_path)) == 2


def test_refresh_offline_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "_fetch", fake_nse([]))
    kw = dict(days=60, log=lambda m: None, symbols=["XYZ"], folder=tmp_path, today=TODAY)
    assert sm.refresh(**kw)["ok"]
    deals_file = sm.files(tmp_path)["deals"]
    before = deals_file.read_bytes()

    monkeypatch.setattr(sm, "_fetch", lambda url, params=None, *, api=False, referer=None: (-1, b""))
    rep = sm.refresh(**kw)
    assert not rep["ok"] and rep["errors"]
    for name in ("deals", "insider", "flows"):
        assert rep["sources"][name]["status"] == "failed"
    assert rep["sources"]["deals"]["last_ok_at"] is not None   # kept from the good run
    assert deals_file.read_bytes() == before
    assert len(sm.load_deals(tmp_path)) == 7 and len(sm.load_insider(tmp_path)) == 4
    assert len(sm.load_flows(tmp_path)) == 1 and len(sm.load_holdings(tmp_path)) == 2


def test_refresh_busy_lock(tmp_path):
    fh = open(tmp_path / ".refresh.lock", "a+")
    assert _try_lock(fh)
    try:
        rep = sm.refresh(days=30, log=lambda m: None, symbols=["XYZ"], folder=tmp_path, today=TODAY)
        assert not rep["ok"]
        assert {s["status"] for s in rep["sources"].values()} == {"skipped"}
        assert rep["errors"] == ["Another smart-money refresh is already running."]
        assert not (tmp_path / "state.json").exists()
        assert sm.refresh_running(tmp_path)
    finally:
        _unlock(fh)
        fh.close()
    assert not sm.refresh_running(tmp_path)
