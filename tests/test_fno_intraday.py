"""Live F&O positioning (scanner/fno_intraday.py): NSE OI-spurts parsing and the live build-up rule."""
from scanner import fno_intraday as fi

PAYLOAD = {"timestamp": "04-Nov-2026 15:40:13", "currTradingDate": "04-Nov-2026", "prevTradingDate": "03-Nov-2026",
           "data": [{"symbol": "COALINDIA", "latestOI": 89650, "prevOI": 53064, "changeInOI": 36586, "avgInOI": 68.95,
                     "volume": 36158, "underlyingValue": 399},
                    {"symbol": "RELIANCE", "latestOI": 754114, "prevOI": 759533, "changeInOI": -5419, "volume": 9,
                     "underlyingValue": 1311},
                    {"symbol": "", "latestOI": 1}]}


def test_parse_reads_nse_time_dates_and_oi():
    d = fi.parse(PAYLOAD)
    assert d["nse_time"] == "2026-11-04T15:40:13+05:30"
    assert d["trade_date"] == "2026-11-04" and d["prev_date"] == "2026-11-03"
    assert [r["symbol"] for r in d["rows"]] == ["COALINDIA", "RELIANCE"]          # a row without a symbol is dropped
    c = d["rows"][0]
    assert c["oi"] == 89650 and c["prev_oi"] == 53064 and c["oi_chg_pct"] == round((89650 / 53064 - 1) * 100, 2)
    assert c["spot_rounded"] == 399
    assert fi.parse({"data": []}) is None and fi.parse({}) is None


def test_live_buildup_needs_a_5pct_oi_change():
    assert fi.classify(1.0, 6.0) == "long_buildup"
    assert fi.classify(-1.0, 6.0) == "short_buildup"
    assert fi.classify(1.0, -6.0) == "short_covering"
    assert fi.classify(-1.0, -6.0) == "long_unwinding"
    assert fi.classify(2.0, 4.9) is None                     # options move OI a lot: under 5% is noise
    assert fi.classify(None, 20.0) is None
