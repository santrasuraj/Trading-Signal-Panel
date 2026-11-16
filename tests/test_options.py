"""Option chains (scanner/options.py): NSE parsing, Black-76 implied volatility and greeks, PCR / max pain / levels /
build-ups on a real NSE chain (NIFTY, 30 Oct 2026 close, expiry 3 Nov), storage that never stores a chain twice,
and the refresh's handling of NSE refusals."""
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scanner import options as o
from scanner.settings import IST

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "options" / "nse_nifty_20261030.json"
EXPIRY = date(2026, 11, 3)


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(o, "OPTIONS_DIR", tmp_path / "options")
    return tmp_path / "options"


def test_parse_nse_chain(payload):
    chain, meta = o.parse_nse(payload, "nifty", EXPIRY)
    assert len(chain) == 104 and chain["strike"].is_monotonic_increasing
    assert meta["symbol"] == "NIFTY" and meta["spot"] == 23053.1 and meta["expiry"] == EXPIRY
    assert meta["time"] == datetime(2026, 10, 30, 15, 40, tzinfo=IST)
    row = chain.set_index("strike").loc[22650]
    assert row["pe_oi"] == 71302 and row["pe_oi_chg"] == 14579 and row["pe_ltp"] == 23.4
    assert math.isnan(row["ce_iv_nse"])                     # NSE's 0 = no figure
    assert chain["ce_oi"].sum() == payload["filtered"]["CE"]["totOI"]


def test_parse_nse_tolerates_junk():
    chain, meta = o.parse_nse({"records": {"data": [{"strikePrice": "x"}, {"strikePrice": 100, "CE": {"lastPrice": 0}}],
                                           "timestamp": "garbage"}}, "ABC", EXPIRY)
    assert list(chain["strike"]) == [100.0] and math.isnan(chain.at[0, "ce_ltp"])
    assert meta["time"] is None and meta["spot"] is None
    assert o.parse_nse({}, "ABC", EXPIRY)[0].empty


def test_implied_vol_round_trip_and_bounds():
    K = np.array([90.0, 100.0, 110.0, 100.0])
    call = np.array([1.0, 1.0, 1.0, 0.0])
    px = o.black76(100.0, K, 0.1, 0.065, np.full(4, 0.2), call)
    assert o.implied_vol(px, 100.0, K, 0.1, 0.065, call) == pytest.approx(np.full(4, 0.2), abs=1e-6)
    # below intrinsic value, above the forward, missing: no volatility can give them
    bad = o.implied_vol(np.array([5.0, 150.0, np.nan]), 100.0, np.array([90.0, 100.0, 100.0]), 0.1, 0.065,
                        np.array([1.0, 1.0, 1.0]))
    assert np.isnan(bad).all()


def test_normal_cdf_matches_math_erf():
    x = np.linspace(-8, 8, 3201)
    exact = np.array([0.5 * math.erfc(-v / math.sqrt(2)) for v in x])     # erfc: exact in the tails too
    got = o._ncdf(x)
    assert np.max(np.abs(got - exact)) < 1e-7
    tail = x < -3                                            # far tails: relative accuracy, not just absolute
    assert np.max(np.abs(got[tail] / exact[tail] - 1)) < 1e-6


def test_greeks_signs_and_parity():
    g_c = o.greeks(100.0, np.array([100.0]), 0.25, 0.0, np.array([0.2]), np.array([1.0]))
    g_p = o.greeks(100.0, np.array([100.0]), 0.25, 0.0, np.array([0.2]), np.array([0.0]))
    assert g_c["delta"][0] - g_p["delta"][0] == pytest.approx(1.0)        # call delta - put delta = 1 (r = 0)
    assert g_c["gamma"][0] == pytest.approx(g_p["gamma"][0]) and g_c["gamma"][0] > 0
    assert g_c["theta"][0] < 0 and g_c["vega"][0] > 0


def test_max_pain_by_hand():
    chain = pd.DataFrame({"strike": [90.0, 100.0, 110.0], "ce_oi": [0.0, 10.0, 100.0], "pe_oi": [100.0, 10.0, 0.0]})
    assert o.max_pain(chain) == 100.0
    assert o.max_pain(chain.assign(ce_oi=0.0, pe_oi=0.0)) is None


def test_buildup_labels():
    price = pd.Series([5.0, -5.0, 5.0, -5.0, 5.0, 5.0, 0.0])
    oi = pd.Series([110.0, 110.0, 90.0, 90.0, 102.0, 50.0, 200.0])
    chg = pd.Series([10.0, 10.0, -10.0, -10.0, 2.0, 50.0, 100.0])
    assert list(o.buildup(price, oi, chg)) == ["long_buildup", "short_buildup", "short_covering", "long_unwinding",
                                               None, "long_buildup", None]   # 2% = noise; new OI; no price move


def test_analyze_real_chain(payload):
    chain, meta = o.parse_nse(payload, "NIFTY", EXPIRY)
    a = o.analyze(chain, meta)
    s, lv = a["summary"], a["levels"]
    f = payload["filtered"]
    assert s["pcr_oi"] == pytest.approx(f["PE"]["totOI"] / f["CE"]["totOI"], abs=0.005)
    assert abs(a["forward"] / a["spot"] - 1) < 0.005 and a["atm"] == 23000.0
    assert a["days_to_expiry"] == pytest.approx(3.99, abs=0.01)
    # on the parity forward a call and a put of the same strike give the same volatility
    for r in a["rows"]:
        if abs(r["strike"] - a["atm"]) <= 300:
            assert r["ce"]["iv_pct"] == pytest.approx(r["pe"]["iv_pct"], abs=0.5), r["strike"]
    assert 5 < s["atm_iv_pct"] < 40 and s["straddle"] > 0 and s["range_low"] < a["spot"] < s["range_high"]
    assert s["max_pain"] in {r["strike"] for r in a["rows"]}
    assert all(x["strike"] >= a["spot"] for x in lv["resistance"]) and all(x["strike"] <= a["spot"] for x in lv["support"])
    assert lv["resistance"][0]["oi"] == max(r["ce"]["oi"] for r in a["rows"] if r["strike"] >= a["spot"])
    assert sum(r["atm"] for r in a["rows"]) == 1
    assert {r["ce"]["buildup"] for r in a["rows"]} <= {*o.BUILDUPS, None}
    assert len(a["readings"]) == 5 and not any("buy" in x.lower() or "sell" in x.lower() for x in a["readings"])
    json.dumps(a, allow_nan=False)                                       # JSON-ready: no NaN anywhere


def test_store_never_stores_a_chain_twice_and_window_change(payload, folder):
    chain, meta = o.parse_nse(payload, "NIFTY", EXPIRY)
    a = o.analyze(chain, meta)
    assert o.store(chain, meta, a) is True
    assert o.store(chain, meta, a) is False                              # same NSE time: nothing written
    later = {**meta, "time": meta["time"] + timedelta(minutes=30)}
    chain2 = chain.assign(ce_oi=chain["ce_oi"] + 100)
    assert o.store(chain2, later, o.analyze(chain2, later)) is True
    snaps = o.load_snapshots(date(2026, 10, 30), "NIFTY", EXPIRY)
    assert len(snaps) == 2 * len(chain)
    summ = pd.read_parquet(o.day_dir(date(2026, 10, 30)) / o.SUMMARY_NAME)
    assert len(summ) == 2 and list(summ.columns) == o.SUMMARY_COLS
    latest = o.load_latest()["chains"]["NIFTY|2026-11-03"]
    assert latest["day"] == "2026-10-30" and latest["time"].startswith("2026-10-30T16:10")
    w = o.window_change(snaps, 15)
    assert w["since"].startswith("2026-10-30T15:40") and w["rows"][23000.0] == (100, 0)
    assert o.window_change(snaps, 60) is None                            # nothing that old yet
    cur, when = o.chain_at(snaps)
    assert when == pd.Timestamp(later["time"]) and cur["ce_oi"].sum() == chain2["ce_oi"].sum()


def test_refresh_stores_chains_and_backs_off_when_refused(payload, folder, monkeypatch):
    calls = []

    def fake_get(path, params):
        calls.append(path)
        if path == "option-chain-contract-info":
            return 200, {"expiryDates": ["10-Nov-2026", "03-Nov-2026"]}
        return 200, payload

    monkeypatch.setattr(o, "_get", fake_get)
    monkeypatch.setattr(o, "_blocked_until", 0.0)
    o._expiry_cache.clear()
    rep = o.refresh({"options": {"underlyings": ["NIFTY"], "expiries": 1}}, log=lambda *_: None)
    assert not rep["errors"] and [c["expiry"] for c in rep["chains"]] == ["2026-11-03"]   # nearest expiry first
    assert o.load_latest()["last_refresh"]["chains"] == 1

    monkeypatch.setattr(o, "_get", lambda path, params: (403, None))
    o._expiry_cache.clear()
    rep = o.refresh({"options": {"underlyings": ["NIFTY", "BANKNIFTY"]}}, log=lambda *_: None)
    assert rep["refused"] and len(rep["errors"]) == 1                    # stops at the first refusal
    monkeypatch.setattr(o, "_get", lambda path, params: pytest.fail("NSE asked again during the pause"))
    rep = o.refresh({"options": {"underlyings": ["NIFTY"]}}, log=lambda *_: None)
    assert rep["refused"] and "waiting" in rep["errors"][0]


def test_settings_validation():
    s = o.settings({"options": {"underlyings": ["nifty", "NIFTY", "../evil", "M&M"], "expiries": 99,
                                "interval_seconds": 1, "risk_free_pct": "x"}})
    assert s["underlyings"] == ["NIFTY", "M&M"] and s["expiries"] == 6
    assert s["interval_seconds"] == o.MIN_INTERVAL_S and s["risk_free_pct"] == o.DEFAULTS["risk_free_pct"]
    assert o.settings(None) == o.DEFAULTS and o.instrument_type("banknifty") == "Indices"
    assert o.instrument_type("RELIANCE") == "Equity"


# ------------------------------------------------------------------ web API (web/api/routers/options.py)
@pytest.fixture
def api(tmp_path, payload, monkeypatch):
    """The API on a temp data folder holding two stored NIFTY chains: NSE's 15:40 close and a copy 30 minutes later
    with 100 more call contracts at every strike."""
    from fastapi.testclient import TestClient

    from scanner import settings
    from web.api import caches
    from web.api.main import create_app
    from web.api.paths import configure
    from web.api.services import options_svc

    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    configure(root, root / "data")
    caches.clear_all()
    chain, meta = o.parse_nse(payload, "NIFTY", EXPIRY)
    o.store(chain, meta, o.analyze(chain, meta))
    later = {**meta, "time": meta["time"] + timedelta(minutes=30)}
    chain2 = chain.assign(ce_oi=chain["ce_oi"] + 100)
    o.store(chain2, later, o.analyze(chain2, later))
    monkeypatch.setattr(options_svc, "today_ist", lambda: date(2026, 10, 30))
    yield TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    configure(settings.ROOT, settings.DATA_DIR)
    caches.clear_all()


def test_api_chain_history_and_status(api):
    from web.api.models import options as M
    st = M.OptStatus.model_validate(api.get("/api/options/status").json())
    assert [(c.symbol, c.expiry) for c in st.chains] == [("NIFTY", "2026-11-03")] and not st.live_running
    r = api.get("/api/options/chain/nifty?window=15")
    assert r.status_code == 200, r.text
    c = M.OptChainResponse.model_validate(r.json())
    assert c.expiry == "2026-11-03" and c.expiries == ["2026-11-03"] and c.time.startswith("2026-10-30T16:10")
    assert len(c.rows) == 104 and c.window_since.startswith("2026-10-30T15:40")
    atm = next(x for x in c.rows if x.atm)
    assert atm.strike == c.atm and atm.ce.oi_chg_window == 100 and atm.pe.oi_chg_window == 0
    assert c.summary.pcr_oi is not None and c.readings and "not a signal" in c.note
    assert api.get("/api/options/chain/NIFTY?window=60").json()["window_since"] is None   # nothing that old
    h = M.OptHistoryResponse.model_validate(api.get("/api/options/history/NIFTY").json())
    assert len(h.t) == 2 == len(h.pcr_oi) and h.max_pain[0] is not None


def test_api_errors(api):
    r = api.get("/api/options/chain/BANKNIFTY")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert api.get("/api/options/chain/NIFTY?expiry=2026-11-10").status_code == 404
    assert api.get("/api/options/chain/NIFTY?expiry=tomorrow").status_code == 422
    assert api.get("/api/options/chain/NIFTY?window=1").status_code == 422
    r = api.post("/api/options/refresh", json={"symbols": ["../etc"]}, headers={"X-Quant-Desk": "1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION"
    assert api.post("/api/options/refresh").status_code == 403           # the CSRF guard header is required


def test_api_refresh_runs_in_the_background(api, monkeypatch):
    import threading
    from web.api.services import options_svc
    gate = threading.Event()

    def fake_refresh(cfg, symbols, log, reset):
        gate.wait(5)
        return {"chains": [{"symbol": s} for s in symbols], "errors": [], "elapsed_s": 1.0}

    monkeypatch.setattr(options_svc.opt, "refresh", fake_refresh)
    monkeypatch.setattr(options_svc, "_run", {**options_svc._run, "thread": None, "state": "idle"})
    h = {"X-Quant-Desk": "1"}
    r = api.post("/api/options/refresh", json={"symbols": ["reliance"]}, headers=h)
    assert r.status_code == 202 and r.json()["run"]["running"]
    busy = api.post("/api/options/refresh", headers=h)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "SCAN_BUSY"
    gate.set()
    options_svc._run["thread"].join(5)
    run = api.get("/api/options/status").json()["run"]
    assert run["state"] == "done" and run["message"].startswith("1 chain")


# ------------------------------------------------------------------ unusual activity and research (Phases 4 and 5)
def test_unusual_activity(payload):
    chain, _ = o.parse_nse(payload, "NIFTY", EXPIRY)
    k = float(chain["strike"].iloc[50])
    window = {"since": "x", "rows": {k: (int(chain.loc[50, "ce_oi"] * 0.5), 0)}}       # calls at k: +50% OI in the window
    out = o.unusual(chain, window, lot=65)
    assert out and all(x["why"] for x in out) and any(x["value_cr"] is not None for x in out)
    values = [x["value_cr"] for x in out if x["value_cr"] is not None]
    assert values == sorted(values, reverse=True)                                     # ranked by premium traded
    assert all(x["value_cr"] is None for x in out[len(values):])                     # no price: last
    if chain.loc[50, "ce_volume"] / chain["ce_volume"].sum() >= o.UNUSUAL_MIN_SHARE:
        assert any(x["strike"] == k and x["side"] == "ce" for x in out)
    assert all(x["value_cr"] is None for x in o.unusual(chain, None, lot=None))


def test_research_claims_on_synthetic_days(folder):
    from scanner import options_research as res
    rows = []
    days = pd.bdate_range("2026-08-03", periods=70)
    for i, d in enumerate(days):
        expiry = days[min(len(days) - 1, (i // 5) * 5 + 4)].date()                   # weekly expiries
        spot = 100 + (i % 5)
        rows.append({"time": pd.Timestamp(d.date().isoformat() + " 15:30", tz=IST), "symbol": "NIFTY",
                     "expiry": expiry.isoformat(), "spot": spot, "forward": spot, "atm": spot, "atm_iv": 12.0,
                     "straddle": 3.0, "expected_move_pct": 3.0, "pcr_oi": 1 + (i % 3) / 10, "pcr_volume": 1.0,
                     "max_pain": 104.0, "ce_oi": 1, "pe_oi": 1, "ce_oi_chg": 0, "pe_oi_chg": 0, "support": 99.0,
                     "resistance": 105.0, "skew_25d": 1.0})
    for d, g in pd.DataFrame(rows).groupby(lambda i: rows[i]["time"].date()):
        o.day_dir(d).mkdir(parents=True, exist_ok=True)
        g[o.SUMMARY_COLS].to_parquet(o.day_dir(d) / o.SUMMARY_NAME, index=False)
    rep = res.report()
    s = rep["studies"][0]
    assert s["symbol"] == "NIFTY" and s["days"] == 70
    assert s["max_pain"]["hit_pct"] == 100.0             # every expiry closes at 104 = max pain
    assert s["expected_move"]["inside_pct"] == 75.0      # moves of 1-4 points vs a straddle of 3: 3 days in 4 inside
    assert s["pcr"]["n"] == 69
    assert "Not enough data" in res.report(min_days=500)["studies"][0]["max_pain"]["verdict"]
