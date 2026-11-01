"""F&O positioning (scanner/fno.py): NSE's participant-wise OI file and the F&O bhavcopy (UDiFF) parsed in their real
formats (checked against the files of 30 Oct 2026), stored without duplicates, and the positions view."""
import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from scanner import fno

DAY = date(2026, 10, 30)
HEADER = ("Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,"
          "Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,"
          "Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,"
          "Total Long Contracts      ,Total Short Contracts")
PART = (f'""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Oct 30, 2026"",,,,,,,,,,,,,,\n'
        f"{HEADER}\n"
        "Client,246926,59938,3291851,222385,2829961,3559948,2847822,4126285,1416834,737854,926229,895144,12083374,9077804\n"
        "DII,46993,6470,256681,4606715,7398,113016,323,123,638,43578,237265,21263,468304,4872159\n"
        "FII,34437,275190,3577558,2659511,607393,1227641,848205,711954,150242,222962,233082,139441,5820233,4867383\n"
        "Pro,32979,19737,747197,384676,1049012,1253468,797414,1315711,832367,828202,1003505,776748,4743225,4297791\n"
        "TOTAL,361335,361335,7873287,7873287,4493764,6154073,4493764,6154073,2400081,1832596,2400081,1832596,23115136,23115136\n")
FO_COLS = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
           "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
           "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")


def fo_row(tp, sym, exp, close, prev, oi, chg, vol=10, strike="", opt="", und=100.0, lot=50):
    return (f"2026-10-30,2026-10-30,FO,NSE,{tp},1,,{sym},,{exp},{exp},{strike},{opt},X,{close},{close},{close},{close},"
            f"{close},{prev},{und},{close},{oi},{chg},{vol},1000000,5,F1,{lot},,,,,")


def fo_zip(rows) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy_NSE_FO_0_0_0_20261030_F_0000.csv", "\n".join([FO_COLS, *rows]) + "\n")
    return buf.getvalue()


def test_parse_participants_real_format():
    df = fno.parse_participants(PART, DAY, "oi")
    assert list(df["client"]) == ["client", "dii", "fii", "pro"]                  # TOTAL dropped
    fii = df.set_index("client").loc["fii"]
    assert fii["fut_idx_long"] == 34437 and fii["fut_idx_short"] == 275190 and fii["idx_put_long"] == 1227641
    assert fii["fut_stk_short"] == 2659511                                       # header with trailing spaces
    with pytest.raises(ValueError):
        fno.parse_participants(PART, date(2026, 10, 29), "oi")                    # another day's file


def test_parse_fo_futures_options_and_walls():
    rows = [
        fo_row("STF", "AAA", "2026-11-23", 110, 100, 10000, 2000),               # +10% price, +25% OI
        fo_row("STF", "AAA", "2026-12-29", 111, 101, 500, 100),
        fo_row("STF", "BBB", "2026-11-23", 90, 100, 9000, -1000),                # -10% price, -10% OI
        fo_row("IDF", "NIFTY", "2026-11-23", 23100, 23000, 650000, 6500, lot=65, und=23053.1),
        fo_row("STO", "AAA", "2026-11-23", 5, 4, 3000, 100, strike="120", opt="CE"),
        fo_row("STO", "AAA", "2026-11-23", 3, 4, 1000, 50, strike="130", opt="CE"),
        fo_row("STO", "AAA", "2026-11-23", 2, 1, 4000, 200, strike="100", opt="PE"),
        fo_row("STO", "AAA", "2026-12-29", 2, 1, 9000, 0, strike="90", opt="PE"),    # later expiry: no wall
    ]
    parsed = fno.parse_fo(fo_zip(rows), DAY)
    assert list(parsed.columns) == fno.FUT_COLS
    f = parsed.set_index("symbol")
    a = f.loc["AAA"]
    assert a["close"] == 110 and a["prev_close"] == 100 and a["oi"] == 10500 and a["oi_chg"] == 2100
    assert a["buildup"] == "long_buildup" and a["chg_pct"] == pytest.approx(10.0)
    assert a["ce_oi"] == 4000 and a["pe_oi"] == 13000 and a["pcr"] == pytest.approx(3.25)
    assert a["call_wall"] == 120 and a["put_wall"] == 100
    assert f.loc["BBB", "buildup"] == "long_unwinding" and f.loc["NIFTY", "kind"] == "index"
    assert f.loc["NIFTY", "basis_pct"] == pytest.approx((23100 / 23053.1 - 1) * 100)
    with pytest.raises(ValueError):
        fno.parse_fo(fo_zip(rows), date(2026, 10, 29))


def test_refresh_stores_each_day_once_and_skips_unpublished(tmp_path, monkeypatch):
    monkeypatch.setattr(fno, "FNO_DIR", tmp_path / "fno")
    monkeypatch.setattr(fno, "_trading_days", lambda n, until: [DAY, date(2026, 11, 2)])
    zipped = fo_zip([fo_row("STF", "AAA", "2026-11-23", 110, 100, 10000, 2000)])

    def get(url):
        if "20261102" in url or "02112026" in url:
            return 404, b""
        return (200, PART.replace("Open Interest", "Trading Volume").encode() if "_vol_" in url else PART.encode()) \
            if "participant" in url else (200, zipped)

    monkeypatch.setattr(fno.nse, "_get_bytes", get)
    rep = fno.refresh(log=lambda *_: None, today=date(2026, 11, 2))
    assert rep["added"] == ["2026-10-30"] and rep["pending"] and not rep["errors"]
    assert len(fno.load_futures()) == 1 and len(fno.load_participants()) == 8   # 4 groups x (oi, vol)
    rep = fno.refresh(log=lambda *_: None, today=date(2026, 11, 2))
    assert rep["added"] == [] and len(fno.load_futures()) == 1                     # nothing fetched twice


def test_positions_view():
    a = fno.parse_participants(PART, DAY, "oi")
    b = a.assign(date=pd.Timestamp(2026, 11, 2), fut_idx_long=a["fut_idx_long"] + 1000)
    v = fno.positions(pd.concat([a, b]), days=20)
    assert v["dates"] == ["2026-10-30", "2026-11-02"]
    fii = v["clients"]["fii"]
    assert fii["fut_net"] == [34437 - 275190, 35437 - 275190] and fii["fut_net_chg"] == [None, 1000.0]
    assert fii["fut_long_pct"][0] == pytest.approx(34437 / (34437 + 275190) * 100)
