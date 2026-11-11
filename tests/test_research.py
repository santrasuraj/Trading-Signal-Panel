"""Late entry (scanner/late_entry.py), the index direction study (scanner/index_study.py), the walk-forward check of
the "working" rule (web/api/services/walkforward.py) and plain-English scans (web/api/services/scan_text.py)."""
import numpy as np
import pandas as pd
import pytest

from scanner import index_study, late_entry


def test_late_entry_joins_later_only_while_the_model_still_holds():
    idx = pd.bdate_range("2022-01-03", periods=400)
    syms = ["WIN", "AVG1", "AVG2"]
    opens = pd.DataFrame(100.0, index=idx, columns=syms)
    opens["WIN"] = 100 * np.exp(np.arange(400) * 0.003)                      # keeps rising: late entries still gain
    member = pd.DataFrame(True, index=idx, columns=syms)
    trades = pd.DataFrame([{"strategy": "s", "symbol": "WIN", "entry_date": idx[i], "exit_date": idx[i + 30]}
                           for i in range(0, 360, 3)] + [{"strategy": "s", "symbol": "WIN", "entry_date": idx[10], "exit_date": idx[13]}])
    rep = late_entry.study(trades, opens, member)
    lags = rep["strategies"]["s"]["lags"]
    assert lags["0"]["n"] == len(trades) and lags["21"]["n"] == len(trades) - 1     # the 3-day trade never reaches day 21
    assert lags["5"]["excess_pct"] > 0 and lags["21"]["excess_pct"] < lags["5"]["excess_pct"]   # less left to gain later
    assert late_entry.lag_for(3) == 5 and late_entry.lag_for(10) == 10 and late_entry.lag_for(15) == 21 and late_entry.lag_for(22) is None


def test_index_study_matches_todays_setup_against_the_index_itself():
    idx = pd.bdate_range("2019-01-01", periods=900)
    rng = np.random.default_rng(2)
    c = pd.Series(10000 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 900))), index=idx)
    m = index_study.match_for(c, "Test index")
    assert m["source"] == "index" and m["setup"] == index_study.setups(c).iloc[-1]
    assert set(m["stats"]) == {"5", "10", "20"} and m["n"] >= 1
    assert "average move" in m["benchmark"]
    assert index_study.match_for(c.iloc[:100]) is None                       # too short to say anything


def test_walk_forward_follows_only_what_was_working_then():
    from web.api.services import walkforward
    idx = pd.bdate_range("2020-01-01", periods=900)
    good = pd.Series(np.exp(np.arange(900) * 0.0012), index=idx)            # beats both benchmarks all along
    bad = pd.Series(np.exp(np.arange(900) * -0.0002), index=idx)
    bench = pd.Series(np.exp(np.arange(900) * 0.0004), index=idx)
    c = pd.DataFrame({"good": good, "bad": bad, "NIFTY 50": bench, "Average stock": bench})
    r = walkforward.replay(c)
    assert r["cagr_pct"]["follow"] > r["cagr_pct"]["all"] > r["cagr_pct"]["ew"] - 50
    assert all(p["working"] == ["good"] for p in r["recent_picks"])
    assert r["verdict"] in ("pays", "no_difference") and r["months"] > 20


def test_plain_english_scan_translation_is_validated(monkeypatch):
    from web.api.errors import ApiException
    from web.api.services import ai_svc, scan_text
    d = {"name": "Breakout", "match": "all", "direction": "long", "explanation": "read as a 20-day breakout",
         "unsupported": "the P/E part",
         "rules": [{"left": "close", "op": ">", "right": {"kind": "field", "value": 0, "field": "high_20_prev", "mult": 1}},
                   {"left": "vol_ratio", "op": ">=", "right": {"kind": "value", "value": 2, "field": "close", "mult": 1}}]}
    out = scan_text.to_scan(d)
    assert out["scan"]["rules"][0]["right"] == {"field": "high_20_prev", "mult": 1.0}
    assert out["scan"]["rules"][1]["right"] == {"value": 2.0} and out["unsupported"] == "the P/E part"
    with pytest.raises(ApiException):
        scan_text.to_scan({**d, "rules": []})                                # nothing expressible -> a clear error
    schema = scan_text._schema()
    assert schema["properties"]["rules"]["items"]["properties"]["left"]["enum"] == list(scan_text.scans.FIELDS)
    monkeypatch.setattr(ai_svc, "_key", lambda: "")
    with pytest.raises(ApiException) as e:
        scan_text.translate("stocks at a 52-week high")
    assert e.value.code == "FEATURE_UNAVAILABLE"                               # no key: never a network call
