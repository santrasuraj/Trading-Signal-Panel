"""Contract tests for the Quant Desk API (web/api) against fixture copies of real result files.

tests/fixtures/root is a cut-down copy of a real data folder (see tests/fixtures/make_fixtures.py): the
latest.json / curves / trades / screener of one real scan, the real intraday.json, journal, NSE caches and a
63-symbol slice of the price store. Each test runs on a private temp copy, so writes (holdings PUT, deleted
files) never touch the fixtures or data/.
"""
from __future__ import annotations

import json
import math
import shutil
import socket
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from pydantic import BaseModel

from scanner import settings
from web.api import caches, models as M
from web.api.paths import configure
from web.api.main import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GUARD = {"X-Quant-Desk": "1"}


# ------------------------------------------------------------------ fixtures
# Read-only tests share one copy (warm caches, fast); tests that write files get a private copy (`env`).
@pytest.fixture(scope="session")
def ro_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("ro") / "root"
    shutil.copytree(FIXTURES / "root", root)
    yield root
    configure(settings.ROOT, settings.DATA_DIR)
    caches.clear_all()


@pytest.fixture
def client(ro_root):
    from web.api.paths import P
    if P.root != ro_root:
        configure(ro_root, ro_root / "data")
        caches.clear_all()
    return TestClient(create_app(warm=False), base_url="http://127.0.0.1")


@pytest.fixture
def env(tmp_path, ro_root):
    root = tmp_path / "root"
    shutil.copytree(FIXTURES / "root", root)
    configure(root, root / "data")
    caches.clear_all()
    yield root
    configure(ro_root, ro_root / "data")
    caches.clear_all()


@pytest.fixture
def mclient(env):
    return TestClient(create_app(warm=False), base_url="http://127.0.0.1")


def latest_fixture(env) -> dict:
    return json.loads((env / "data" / "results" / "latest.json").read_text(encoding="utf-8"))


def write_latest(env, lt: dict) -> None:
    (env / "data" / "results" / "latest.json").write_text(json.dumps(lt), encoding="utf-8")
    caches.clear_all()


# ------------------------------------------------------------------ shape checking
def _model_of(annotation):
    """The BaseModel inside an annotation like `X | None`, `list[X]` or `dict[str, X]` (else None)."""
    origin = typing.get_origin(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, "one"
    if origin in (list, tuple):
        inner = _model_of(typing.get_args(annotation)[0]) if typing.get_args(annotation) else None
        return (inner[0], "list") if inner else None
    if origin is dict:
        inner = _model_of(typing.get_args(annotation)[1])
        return (inner[0], "dict") if inner else None
    for a in typing.get_args(annotation):         # Optional / Union
        if a is not type(None):
            found = _model_of(a)
            if found:
                return found
    return None


def assert_shape(model: type[BaseModel], obj, path: str = "$") -> None:
    """Every declared field is present (null allowed), recursively; no NaN; then a full pydantic validation."""
    assert isinstance(obj, dict), f"{path}: expected object, got {type(obj).__name__}"
    for name, field in model.model_fields.items():
        key = field.alias or name
        assert key in obj, f"{path}.{key} missing"
        val = obj[key]
        inner = _model_of(field.annotation)
        if inner is None or val is None:
            continue
        sub, kind = inner
        if kind == "one":
            assert_shape(sub, val, f"{path}.{key}")
        elif kind == "list":
            for i, v in enumerate(val[:50]):
                assert_shape(sub, v, f"{path}.{key}[{i}]")
        else:
            for k, v in list(val.items())[:50]:
                assert_shape(sub, v, f"{path}.{key}.{k}")
    if path == "$":
        model.model_validate(obj)
        _no_nan(obj)


def _no_nan(v, path="$"):
    if isinstance(v, float):
        assert math.isfinite(v), f"{path}: non-finite number"
    elif isinstance(v, dict):
        for k, x in v.items():
            _no_nan(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _no_nan(x, f"{path}[{i}]")


def get_ok(client, url, model):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code, r.text[:500])
    assert r.headers.get("cache-control") == "no-store"
    body = r.json()
    assert_shape(model, body)
    return body


# Every GET endpoint of the Final API contract, with its response model.
GET_ENDPOINTS = [
    ("/api/health", M.Health), ("/api/status", M.AppStatus), ("/api/overview", M.OverviewResponse),
    ("/api/market/breadth?range=1y", M.BreadthResponse), ("/api/strategies", M.StrategyListResponse),
    ("/api/strategies?horizon=swing", M.StrategyListResponse), ("/api/strategies/momentum", M.StrategyDetail),
    ("/api/strategies/earnings_gap", M.StrategyDetail), ("/api/strategies/rsi2_pullback", M.StrategyDetail),
    ("/api/strategies/momentum/curve?range=3y", M.CurveResponse),
    ("/api/strategies/momentum/trades?page_size=20", M.TradesPage), ("/api/signals", M.SignalsResponse),
    ("/api/screener?preset=all", M.ScreenerResponse), ("/api/screener?preset=momentum", M.ScreenerResponse),
    ("/api/sparklines?symbols=IGIL,TCS,NIFTY50&days=30", M.SparklinesResponse), ("/api/symbols", M.SymbolsResponse),
    ("/api/chart/IGIL?range=1y&indicators=sma20,sma50,sma200,ema21,bb_upper,bb_mid,bb_lower,rsi14,macd,macd_signal,macd_hist,vol_avg20",
     M.ChartResponse),
    ("/api/chart/NIFTY50?tf=1w&range=max", M.ChartResponse), ("/api/stock/IGIL", M.StockSnapshot),
    ("/api/stock/NIFTY50", M.StockSnapshot), ("/api/holdings", M.HoldingsResponse), ("/api/paper", M.PaperListResponse),
    ("/api/paper/momentum", M.PaperDetail), ("/api/market/movers", M.MoversResponse),
    ("/api/market/sectors", M.SectorsResponse), ("/api/market/factors", M.FactorsResponse),
    ("/api/market/results?days=14", M.ResultsResponse), ("/api/scan/history", M.ScanHistory),
    ("/api/scan/log?lines=20", M.ScanLog), ("/api/fyers/status", M.FyersStatus), ("/api/config", M.ConfigResponse),
    ("/api/costs/preview?value=33333", M.CostPreview), ("/api/data/health", M.DataHealth),
    ("/api/intraday", M.IntradayResponse),
]


@pytest.mark.parametrize("url,model", GET_ENDPOINTS, ids=[u for u, _ in GET_ENDPOINTS])
def test_endpoint_shape(client, url, model):
    get_ok(client, url, model)


def test_openapi_lists_every_contract_path(client):
    spec = client.get("/api/openapi.json").json()
    paths = set(spec["paths"])
    for url, _ in GET_ENDPOINTS:
        p = url.split("?")[0]
        p = p.replace("/momentum", "/{key}").replace("/earnings_gap", "/{key}").replace("/rsi2_pullback", "/{key}")
        p = p.replace("/IGIL", "/{symbol}").replace("/NIFTY50", "/{symbol}")
        assert p in paths, p
    for p in ("/api/holdings/import/fyers", "/api/scan", "/api/fyers/login", "/api/fyers/login/complete",
              "/api/intraday/run"):
        assert p in paths, p
    # every response field is "required" in the schema, so generated TS has no optional fields
    assert set(spec["components"]["schemas"]["AsOf"]["required"]) >= {"live_source", "complete_upto", "stale"}


# ------------------------------------------------------------------ normalisation and honesty
def test_strategy_list_normalises_latest(client):
    body = get_ok(client, "/api/strategies", M.StrategyListResponse)
    lt = latest_fixture_from(client)
    assert [s["key"] for s in body["strategies"]] == [s["key"] for s in lt["strategies"]]   # daily.py order
    assert {s["key"] for s in body["rejected"]} == {s["key"] for s in lt["rejected_strategies"]}
    assert all(s["lifecycle"] == "rejected" and s["comparison_only"] for s in body["rejected"])
    assert body["rejected_catalogue"] == []                       # B4 present: no catalogue fallback
    b = body["benchmarks"]
    assert b["survivorship_gap_pct"] == pytest.approx(b["average_stock"]["cagr_pct"] - b["nifty500"]["cagr_pct"], abs=0.01)
    for s in body["strategies"]:
        assert len(s["spark"]) <= 120
        if s["timing"]:
            t = s["timing"]
            assert t["consistent"] == (t["low"] - 0.05 <= t["base_cagr_pct"] <= t["high"] + 0.05)
        assert s["comparison_only"] == (s["status"] == "not-working")
        assert s["edges"]["primary"] == ("nifty" if s["universe"] == "etfs" else "ew")


def latest_fixture_from(client) -> dict:
    from web.api.services import data
    return data.latest()


def test_detail_windows_and_benchmarks(client):
    d = get_ok(client, "/api/strategies/momentum", M.StrategyDetail)
    m = d["metrics"]
    assert m["m3"]["cagr_pct"] is None and m["m3"]["return_pct"] is not None    # windows use return_pct
    assert m["full"]["factor_benchmark_name"] == "Nifty200 Momentum 30"
    eg = get_ok(client, "/api/strategies/earnings_gap", M.StrategyDetail)
    assert eg["metrics"]["full"]["factor_benchmark"] is None                    # {} in latest.json -> null
    assert eg["strategy"]["factor_benchmark_name"] is None                     # '' -> null
    assert d["rules"]["source"] == "scan" and d["rules"]["plain_rules"]
    assert all("qty" not in p for p in d["positions"])                         # compounded qty never exposed
    assert all("qty" not in t and "pnl" not in t for t in d["recent_trades"])
    assert d["evidence"]["catalogue_id"] == "L1"
    years = [y["year"] for y in d["yearly"]]
    assert years == sorted(years) and d["yearly"][0]["partial"]
    assert all(len(r["months"]) == 12 for r in d["monthly"])


def test_legacy_latest_is_flagged_and_still_served(mclient, env):
    lt = json.loads((FIXTURES / "legacy_latest.json").read_text(encoding="utf-8"))
    lt.pop("indices", None)
    write_latest(env, lt)
    st = get_ok(mclient, "/api/status", M.AppStatus)
    assert st["latest"]["legacy_producer"] is True
    assert st["features"]["trades_artifact"] is False and st["features"]["screener_artifact"] is False
    body = get_ok(mclient, "/api/strategies", M.StrategyListResponse)
    assert body["rejected"] == [] and body["rejected_catalogue"]               # catalogue fallback before B4
    d = get_ok(mclient, "/api/strategies/momentum", M.StrategyDetail)
    assert d["rules"]["source"] == "config"
    assert d["trades_available"] is False
    r = mclient.get("/api/screener")                                            # artifact from another scan_id
    assert r.status_code == 501 and r.json()["error"]["details"]["feature"] == "screener"
    get_ok(mclient, "/api/overview", M.OverviewResponse)


# ------------------------------------------------------------------ sizing (review A1)
def test_buy_sizing_equals_scan_without_allocations(mclient, env):
    lt = latest_fixture(env)
    body = get_ok(mclient, "/api/signals", M.SignalsResponse)
    assert body["allocation_source"] == "none" and body["sized_like_scan"] is True
    api = {(o["strategy_key"], o["symbol"]): o for g in body["groups"] for o in g["orders"]}
    n = 0
    for s in lt["strategies"]:
        for a in s["actions"]:
            if a["action"] == "BUY":
                o = api[(s["key"], a["symbol"])]
                assert o["qty"] == a["qty"] and o["qty_basis"] == "sized"
                n += 1
    assert n >= 1


def _with_sell(env, qty_in_model: int = 5026):
    lt = latest_fixture(env)
    mom = next(s for s in lt["strategies"] if s["key"] == "momentum")
    pos = mom["positions"][0]
    pos["qty"] = qty_in_model
    mom["actions"].append({"action": "SELL", "symbol": pos["symbol"], "reason": "dropped from ranking",
                           "price": pos["last_price"], "qty": qty_in_model, "amount": qty_in_model * pos["last_price"],
                           "stop": None, "results_on": None, "results_warning": False, "provisional": False})
    write_latest(env, lt)
    return pos


def test_sell_is_never_the_compounded_backtest_qty(mclient, env):
    pos = _with_sell(env)
    from web.api.services import data
    curve_last = float(data.curves()["momentum"].dropna().iloc[-1])
    body = get_ok(mclient, "/api/signals", M.SignalsResponse)
    o = next(o for g in body["groups"] for o in g["orders"] if o["action"] == "SELL")
    assert o["qty_basis"] == "model_weight"
    weight = pos["qty"] * pos["last_price"] / (500000 * curve_last) * 100
    assert o["qty"] == math.floor(500000 * round(weight, 2) / 100 / pos["last_price"])
    assert o["qty"] != pos["qty"] and o["qty"] < pos["qty"]
    assert o["risk_amount"] is None


def test_sell_uses_your_holding_when_you_hold_it(mclient, env):
    pos = _with_sell(env)
    (env / "holdings.csv").write_text(f"symbol,qty,buy_price,buy_date,stop_loss_pct,target_pct\n{pos['symbol']},120,70,,,\n",
                                      encoding="utf-8")
    caches.clear_all()
    body = get_ok(mclient, "/api/signals", M.SignalsResponse)
    o = next(o for g in body["groups"] for o in g["orders"] if o["action"] == "SELL")
    assert (o["qty"], o["qty_basis"], o["you_hold_qty"]) == (120, "your_holding", 120)


def test_allocations_query_resizes_buys(mclient, env):
    lt = latest_fixture(env)
    eg = next(s for s in lt["strategies"] if s["key"] == "earnings_gap")
    a = next(x for x in eg["actions"] if x["action"] == "BUY")
    body = get_ok(mclient, "/api/signals?allocations=momentum:60,earnings_gap:40", M.SignalsResponse)
    assert body["allocation_source"] == "query" and body["sized_like_scan"] is False
    o = next(o for g in body["groups"] for o in g["orders"] if o["symbol"] == a["symbol"])
    assert o["qty"] == math.floor(500000 * 0.40 / eg["max_positions"] / a["price"])
    assert "No allocation" in (body["allocation_warning"] or "")
    r = mclient.get("/api/signals?allocations=nope:10")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION"


# ------------------------------------------------------------------ no network in GET handlers
def test_get_handlers_never_touch_the_network(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access from a GET handler")
    real_connect = socket.socket.connect

    def connect(sock, address, *a, **k):     # the event loop's own loopback socketpair is fine
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            boom()
        return real_connect(sock, address, *a, **k)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setattr(requests, "get", boom)
    for url, model in GET_ENDPOINTS:
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])


def test_status_is_file_stat_only(client, monkeypatch):
    import scanner.providers as providers
    monkeypatch.setattr(providers, "get_fyers", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Fyers call")))
    monkeypatch.setattr(providers.FyersProvider, "check_login", lambda self: (_ for _ in ()).throw(AssertionError("Fyers")))
    from web.api.services import fyers_svc
    monkeypatch.setattr(fyers_svc, "_profile", lambda p: (_ for _ in ()).throw(AssertionError("Fyers")))
    get_ok(client, "/api/status", M.AppStatus)


# ------------------------------------------------------------------ error envelope and security
def _err(r, status, code):
    assert r.status_code == status, (r.status_code, r.text[:300])
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "hint", "details"}
    assert body["error"]["code"] == code
    M.ApiError.model_validate(body)
    return body["error"]


def test_error_envelope_not_found_and_validation(client):
    _err(client.get("/api/strategies/nope"), 404, "NOT_FOUND")
    _err(client.get("/api/chart/NOPE"), 404, "NOT_FOUND")
    _err(client.get("/api/nope"), 404, "NOT_FOUND")
    e = _err(client.get("/api/strategies/momentum/curve?range=5y"), 422, "VALIDATION")
    assert e["details"]["errors"]
    _err(client.get("/api/chart/IGIL?indicators=vwap"), 422, "VALIDATION")
    _err(client.get("/api/strategies/momentum/trades?sort=pnl"), 422, "VALIDATION")
    _err(client.get("/api/sparklines?symbols=" + ",".join(f"S{i}" for i in range(501))), 422, "VALIDATION")


def test_no_scan(mclient, env):
    (env / "data" / "results" / "latest.json").unlink()
    caches.clear_all()
    _err(mclient.get("/api/overview"), 404, "NO_SCAN")
    _err(mclient.get("/api/strategies"), 404, "NO_SCAN")
    st = get_ok(mclient, "/api/status", M.AppStatus)
    assert st["latest"] is None and st["ticker"] is None
    get_ok(mclient, "/api/holdings", M.HoldingsResponse)


def test_feature_unavailable(mclient, env):
    (env / "data" / "results" / "screener.parquet").unlink()
    caches.clear_all()
    e = _err(mclient.get("/api/screener"), 501, "FEATURE_UNAVAILABLE")
    assert e["details"] == {"feature": "screener"}


def test_internal_error_envelope(client, monkeypatch):
    from web.api.services import settings_svc
    monkeypatch.setattr(settings_svc, "cost_preview", lambda v: 1 / 0)
    e = _err(TestClient(client.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
             .get("/api/costs/preview?value=100"), 500, "INTERNAL")
    assert "ZeroDivisionError" in e["message"]


def test_api_log_moves_with_the_data_folder(env):
    from web.api import errors
    files = [h.baseFilename for h in errors.log.handlers if isinstance(h, errors._ApiLog)]
    assert [Path(f) for f in files] == [(env / "data" / "logs" / "api.log").absolute()]     # never the real data/logs


def test_mutations_need_the_guard_header(client):
    _err(client.put("/api/holdings", json={"rows": []}), 403, "CSRF")
    _err(client.post("/api/scan", json={}), 403, "CSRF")
    _err(client.post("/api/fyers/login", json={"mode": "window"}), 403, "CSRF")
    _err(client.post("/api/scan", json={}, headers={"X-Quant-Desk": "0"}), 403, "CSRF")


def test_trusted_host_only(client):
    _err(client.get("/api/health", headers={"Host": "evil.example.com"}), 403, "FORBIDDEN_HOST")
    _err(client.get("/", headers={"Host": "127.0.0.1.nip.io:8600"}), 403, "FORBIDDEN_HOST")
    assert client.get("/api/health", headers={"Host": "localhost:8600"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "127.0.0.1:5173"}).status_code == 200


def test_spa_fallback_blocks_path_traversal(client):
    for url in ("/..%2f..%2fconfig.yaml", "/../../.env", "/%2e%2e/%2e%2e/.env"):
        r = client.get(url)
        assert "FYERS" not in r.text and "capital:" not in r.text


# ------------------------------------------------------------------ scan
def test_scan_busy(client, monkeypatch):
    from web.api.services import scan_runner
    monkeypatch.setattr(scan_runner, "running_scan", lambda: {"started": "12:15:09", "by": "schedule", "pid": 42})
    e = _err(client.post("/api/scan", json={"update": False}, headers=GUARD), 409, "SCAN_BUSY")
    assert e["details"] == {"started": "12:15:09", "by": "schedule", "pid": 42}
    st = get_ok(client, "/api/status", M.AppStatus)["scan"]
    assert st["state"] == "running" and st["by"] == "schedule" and st["started_at"].endswith("12:15:09+05:30")


def test_scan_start_and_status_merge(mclient, env, monkeypatch):
    from web.api.services import scan_runner
    launched = {}

    class FakePopen:
        pid = 4242

        def __init__(self, args, **kw):
            launched["args"], launched["kw"] = args, kw

        def poll(self):
            return None
    monkeypatch.setattr(scan_runner.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(scan_runner, "running_scan", lambda: None)
    monkeypatch.setattr(scan_runner, "_proc", {"popen": None, "at": 0.0, "update": None})
    r = mclient.post("/api/scan", json={"update": False}, headers=GUARD)
    assert r.status_code == 202, r.text
    body = r.json()
    M.ScanAccepted.model_validate(body)
    assert body["accepted"] and body["status"]["state"] == "starting" and body["status"]["running"]
    assert "--no-update" in launched["args"] and "--status" in launched["args"]
    assert not (env / "data" / "results" / "status.json").exists()        # removed before launching
    (env / "data" / "results" / "status.json").write_text(json.dumps(
        {"state": "running", "message": "Downloading TCS (10/500)", "progress": 0.02, "started": 1792734489.0}))
    st = get_ok(mclient, "/api/status", M.AppStatus)["scan"]
    assert st["state"] == "running" and st["progress_pct"] == 2.0 and st["started_at"].endswith("+05:30")
    _err(mclient.post("/api/scan", json={}, headers=GUARD), 409, "SCAN_BUSY")
    # final state written, process still exiting (e.g. sending Telegram): done, never back to "starting"
    (env / "data" / "results" / "status.json").write_text(json.dumps(
        {"state": "done", "message": "Done in 80s", "progress": 1.0, "started": 1792734489.0}))
    st = get_ok(mclient, "/api/status", M.AppStatus)["scan"]
    assert st["state"] == "done" and not st["running"]


def test_scan_that_dies_at_once_is_failed_not_starting(mclient, env, monkeypatch):
    from web.api.services import scan_runner

    class DeadPopen:
        pid = 4243

        def __init__(self, args, **kw):
            pass

        def poll(self):
            return 1
    monkeypatch.setattr(scan_runner.subprocess, "Popen", DeadPopen)
    monkeypatch.setattr(scan_runner, "running_scan", lambda: None)
    monkeypatch.setattr(scan_runner, "_proc", {"popen": None, "at": 0.0, "update": None, "wall": 0.0})
    r = mclient.post("/api/scan", json={"update": False}, headers=GUARD)
    assert r.status_code == 202, r.text
    st = r.json()["status"]
    assert st["state"] == "failed" and not st["running"] and st["exit_code"] == 1


def test_scan_history_and_log(client):
    h = get_ok(client, "/api/scan/history", M.ScanHistory)
    assert h["scans"] and h["scans"][0]["strategies"] == 13
    log = get_ok(client, "/api/scan/log?lines=5", M.ScanLog)
    assert len(log["lines"]) <= 5


def test_status_progress_is_percent(client):
    st = get_ok(client, "/api/status", M.AppStatus)
    assert st["scan"]["state"] == "done" and st["scan"]["progress_pct"] == 100.0
    assert st["scan"]["started_at"].endswith("+05:30")


# ------------------------------------------------------------------ holdings
def test_holdings_round_trip(mclient, env):
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    assert {i["symbol"] for i in h["inputs"]} == {"IGIL", "TCS"}
    # an empty buy date is null, never "NaT" (the UI would call it a future date and block the save)
    assert {i["symbol"]: i["buy_date"] for i in h["inputs"]} == {"IGIL": "2026-09-01", "TCS": None}
    assert h["health_stale"] is True                          # the fixture scan had no holdings
    # rows added after the scan get a first check on the scan's prices and say so
    assert [r["symbol"] for r in h["rows"]] == [i["symbol"] for i in h["inputs"]]
    assert all(any(a.startswith("Added after the last scan") or a.startswith("No price data") for a in r["alerts"])
               for r in h["rows"])
    rows = [{"symbol": "infy", "qty": 5, "buy_price": 1500, "buy_date": "2026-01-02", "stop_loss_pct": 8, "target_pct": 20},
            {"symbol": "TCS", "qty": -1, "buy_price": 3000, "buy_date": None, "stop_loss_pct": None, "target_pct": None},
            {"symbol": "ZZZNOTREAL", "qty": 1, "buy_price": 10, "buy_date": "2999-01-01", "stop_loss_pct": None,
             "target_pct": None},
            {"symbol": "ZZZUNKNOWN", "qty": 1, "buy_price": 10, "buy_date": None, "stop_loss_pct": None, "target_pct": None}]
    r = mclient.put("/api/holdings", json={"rows": rows}, headers=GUARD)
    assert r.status_code == 200, r.text
    body = r.json()
    M.HoldingsPutResponse.model_validate(body)
    assert body["saved"] == 2
    assert [(x["index"], x["reason"]) for x in body["rejected"]] == [(1, "negative quantity"), (2, "buy date is in the future")]
    assert body["unknown_symbols"] == ["ZZZUNKNOWN"]
    text = (env / "holdings.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "symbol,qty,buy_price,buy_date,stop_loss_pct,target_pct"
    assert "INFY" in text and "ZZZUNKNOWN" in text and "ZZZNOTREAL" not in text
    caches.clear_all()
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    assert {i["symbol"] for i in h["inputs"]} == {"INFY", "ZZZUNKNOWN"}
    # a "NaT" buy date sent back by an older UI keeps the row (no date) instead of rejecting it
    r = mclient.put("/api/holdings", json={"rows": [{"symbol": "TCS", "qty": 1, "buy_price": 3000, "buy_date": "NaT"}]},
                    headers=GUARD)
    assert r.status_code == 200 and r.json()["saved"] == 1 and r.json()["rejected"] == []


def test_renamed_holding_is_not_counted_twice(mclient, env):
    lt = latest_fixture(env)
    lt["holdings"] = [{"symbol": "TMPV", "company": "Tata Motors PV", "qty": 10, "buy_price": 700, "price": 400,
                       "change_pct": 1.0, "level": "ok", "alerts": ["TATAMOTORS is now traded as TMPV"]}]
    write_latest(env, lt)
    (env / "holdings.csv").write_text("symbol,qty,buy_price,buy_date,stop_loss_pct,target_pct\nTATAMOTORS,10,700,,,\n",
                                      encoding="utf-8")
    caches.clear_all()
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    assert [r["symbol"] for r in h["rows"]] == ["TMPV"] and h["totals"]["value"] == 4000.0


def test_holdings_follow_holdings_csv_after_the_scan(mclient, env):
    """A holding removed after the scan disappears (rows, totals, alerts); an edited one is restated."""
    lt = latest_fixture(env)
    lt["holdings"] = [{"symbol": "TCS", "company": "TCS", "qty": 1, "buy_price": 3000, "price": 2500, "change_pct": 1.0,
                       "pnl_pct": -16.67, "pnl_amount": -500, "stop_price": 2760, "target_price": 3600,
                       "level": "danger", "alerts": ["STOP-LOSS HIT: down more than 8% from your buy price"]}]
    write_latest(env, lt)
    head = "symbol,qty,buy_price,buy_date,stop_loss_pct,target_pct\n"
    (env / "holdings.csv").write_text(head + "TCS,1,3000,,,\n", encoding="utf-8")
    caches.clear_all()
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    assert [(r["symbol"], r["level"]) for r in h["rows"]] == [("TCS", "danger")] and h["totals"]["danger"] == 1
    (env / "holdings.csv").write_text(head, encoding="utf-8")
    caches.clear_all()
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    assert h["rows"] == [] and h["totals"]["count"] == 0 and h["totals"]["danger"] == 0
    (env / "holdings.csv").write_text(head + "TCS,2,2400,,,\n", encoding="utf-8")
    caches.clear_all()
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    r = h["rows"][0]
    assert (r["qty"], r["buy_price"], r["value"], r["pnl_amount"], r["level"]) == (2, 2400, 5000, 200, "ok")
    assert r["stop_price"] == 2208 and h["health_stale"] is True
    assert not any(a.startswith("STOP-LOSS") for a in r["alerts"])


def test_holdings_save_reports_a_locked_csv(mclient, env, monkeypatch):
    from web.api.services import holdings_svc

    def locked(df):
        raise PermissionError(13, "The process cannot access the file")
    monkeypatch.setattr(holdings_svc, "save_holdings", locked)
    e = _err(mclient.put("/api/holdings", json={"rows": [{"symbol": "TCS", "qty": 1}]}, headers=GUARD), 409, "INTERNAL")
    assert "Excel" in e["message"]


def test_fyers_import_requires_todays_login(mclient, env):
    (env / "data" / "fyers_token.json").unlink(missing_ok=True)
    r = mclient.post("/api/holdings/import/fyers", headers=GUARD)
    assert r.status_code == 409 and r.json()["error"]["code"] in ("FYERS_LOGIN_REQUIRED", "FYERS_NOT_CONFIGURED")


class _FakeFyers:
    """FyersProvider stand-in: _call(fn, payload, bucket) returns a canned reply for api.holdings."""

    def __init__(self, reply: dict):
        self.reply, self.api = reply, SimpleNamespace(holdings=lambda: None)

    def _call(self, fn, payload=None, bucket="data"):
        assert fn is self.api.holdings and bucket == "user"
        return self.reply


def test_fyers_import_preview_maps_rows(mclient, env, monkeypatch):
    from web.api.services import fyers_svc
    raw = [{"symbol": "NSE:SBIN-EQ", "quantity": 10, "costPrice": 712.5},
           {"symbol": "NSE:M&M-EQ", "quantity": 2, "costPrice": 2900.0}]
    monkeypatch.setattr(fyers_svc, "get_client", lambda: _FakeFyers({"s": "ok", "holdings": raw}))
    r = mclient.post("/api/holdings/import/fyers", headers=GUARD)
    body = r.json()
    M.FyersImportResponse.model_validate(body)
    assert [x["symbol"] for x in body["rows"]] == ["SBIN", "M&M"] and body["count"] == 2
    assert not (env / "holdings.csv").read_text(encoding="utf-8").count("SBIN")      # preview only


def test_fyers_import_failure_is_not_an_empty_account(mclient, env, monkeypatch):
    from web.api.services import fyers_svc
    monkeypatch.setattr(fyers_svc, "get_client",
                        lambda: _FakeFyers({"s": "error", "code": -99, "message": "ConnectionError"}))
    e = _err(mclient.post("/api/holdings/import/fyers", headers=GUARD), 502, "FYERS_AUTH")
    assert "ConnectionError" in e["message"]


# ------------------------------------------------------------------ fyers
def test_fyers_status_never_leaks_secrets(mclient, monkeypatch, env):
    monkeypatch.setenv("FYERS_CLIENT_ID", "ABCD1234EF-100")
    monkeypatch.setenv("FYERS_SECRET_KEY", "supersecret")
    (env / "data" / "fyers_token.json").write_text(json.dumps(
        {"client_id": "ABCD1234EF-100", "access_token": "tok-SECRET-123", "created": "2026-01-01T08:00:00+05:30"}))
    body = get_ok(mclient, "/api/fyers/status", M.FyersStatus)
    text = json.dumps(body)
    assert "supersecret" not in text and "tok-SECRET-123" not in text and "ABCD1234EF" not in text
    assert body["client_id_masked"] == "ABCD****-100" and body["token_present"] and not body["logged_in_today"]
    assert body["login_modes"] == ["paste", "window"]


def test_fyers_status_says_when_rate_limit_protection_is_on(mclient, monkeypatch, env):
    from scanner import fyers_limits
    monkeypatch.setenv("FYERS_CLIENT_ID", "ABCD1234EF-100")
    monkeypatch.setenv("FYERS_SECRET_KEY", "supersecret")
    today = fyers_limits.ist_today().isoformat()
    (env / "data" / "fyers_token.json").write_text(json.dumps(
        {"client_id": "ABCD1234EF-100", "access_token": "tok-123", "created": today + "T08:00:00+05:30"}))
    assert fyers_limits.STATE_FILE == env / "data" / "fyers_usage.json"       # configure() isolates the usage file
    fyers_limits.STATE_FILE.write_text(json.dumps({"date": today, "strikes": 2, "pause_until": 0.0, "buckets": {}}),
                                       encoding="utf-8")
    body = get_ok(mclient, "/api/fyers/status", M.FyersStatus)
    assert body["logged_in_today"] and "rate-limit protection" in body["note"]


def test_fyers_login_window_and_code_extraction(mclient, monkeypatch, env):
    from web.api.services import fyers_svc
    monkeypatch.setattr(fyers_svc, "_pending", {"session": None, "state": None, "expires": 0.0})
    (env / "1_login.bat").write_text("@echo off\n", encoding="utf-8")
    started = {}
    monkeypatch.setattr(fyers_svc.subprocess, "Popen", lambda args, **kw: started.setdefault("args", args))
    r = mclient.post("/api/fyers/login", json={"mode": "window"}, headers=GUARD)
    assert r.status_code == 200 and r.json()["mode"] == "window" and "1_login.bat" in started["args"][-1]
    assert fyers_svc.extract_code("http://127.0.0.1:8000/cb?s=ok&auth_code=AB.CD&state=xyz") == ("AB.CD", "xyz")
    assert fyers_svc.extract_code("  RAWCODE ") == ("RAWCODE", None)
    e = _err(mclient.post("/api/fyers/login/complete", json={"redirect_url": "http://x/?auth_code=1"}, headers=GUARD),
             422, "VALIDATION")
    assert "expired" in e["message"] or "not started" in e["message"]


def test_fyers_paste_login_complete_writes_token(mclient, env, monkeypatch):
    from web.api.services import fyers_svc
    monkeypatch.setenv("FYERS_CLIENT_ID", "ABCD1234EF-100")
    monkeypatch.setenv("FYERS_SECRET_KEY", "s3cret")

    class FakeSession:
        def __init__(self, **kw):
            self.kw = kw

        def generate_authcode(self):
            return "https://api-t1.fyers.in/api/v3/generate-authcode?state=" + self.kw["state"]

    import fyers_apiv3.fyersModel as fm
    monkeypatch.setattr(fm, "SessionModel", FakeSession)
    exchanged = {}

    def exchange(session, code):            # the token request (with a timeout) never leaves the test
        exchanged["code"] = code
        return {"access_token": "NEWTOKEN"}
    monkeypatch.setattr(fyers_svc, "_exchange_code", exchange)
    monkeypatch.setattr(fyers_svc.providers.FyersProvider, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(fyers_svc, "_profile", lambda p: (True, "Test User"))
    r = mclient.post("/api/fyers/login", json={"mode": "paste"}, headers=GUARD).json()
    M.FyersLoginResponse.model_validate(r)
    state = r["login_url"].split("state=")[1]
    _err(mclient.post("/api/fyers/login/complete", json={"redirect_url": f"http://x/?auth_code=C&state=bad"}, headers=GUARD),
         502, "FYERS_AUTH")
    r = mclient.post("/api/fyers/login", json={"mode": "paste"}, headers=GUARD).json()
    state = r["login_url"].split("state=")[1]
    done = mclient.post("/api/fyers/login/complete", json={"redirect_url": f"http://x/?auth_code=C&state={state}"},
                       headers=GUARD)
    assert done.status_code == 200, done.text
    body = done.json()
    M.FyersLoginCompleteResponse.model_validate(body)
    assert body["ok"] and body["user_name"] == "Test User" and body["status"]["logged_in_today"]
    assert exchanged["code"] == "C"
    tok = json.loads((env / "data" / "fyers_token.json").read_text(encoding="utf-8"))
    assert set(tok) == {"client_id", "access_token", "created"} and tok["access_token"] == "NEWTOKEN"
    assert "NEWTOKEN" not in done.text
    # FYERS rate-limit protection (or a network blip) during the profile check is not a rejected login
    monkeypatch.setattr(fyers_svc, "_profile", lambda p: (None, None))
    r = mclient.post("/api/fyers/login", json={"mode": "paste"}, headers=GUARD).json()
    state = r["login_url"].split("state=")[1]
    done = mclient.post("/api/fyers/login/complete", json={"redirect_url": f"http://x/?auth_code=C&state={state}"},
                        headers=GUARD).json()
    assert done["ok"] is True and done["user_name"] is None and done["status"]["verified"] is None


def test_profile_check_tells_rejected_from_unknown():
    from scanner.fyers_limits import FyersRateLimited
    from web.api.services import fyers_svc

    def provider(result):
        def call(fn, payload=None, bucket="data"):
            assert bucket == "user"
            if isinstance(result, Exception):
                raise result
            return result
        return SimpleNamespace(api=SimpleNamespace(get_profile=lambda: None), _call=call)
    assert fyers_svc._profile(provider({"s": "ok", "data": {"name": "A B"}})) == (True, "A B")
    assert fyers_svc._profile(provider(fyers_svc.providers.FyersAuthError("expired"))) == (False, None)
    assert fyers_svc._profile(provider(FyersRateLimited("stopped"))) == (None, None)
    assert fyers_svc._profile(provider({"s": "error", "code": -99, "message": "ConnectionError"})) == (None, None)


# ------------------------------------------------------------------ market, chart, overview details
def test_chart_alignment_and_weekly_stamps(client):
    d = get_ok(client, "/api/chart/IGIL?range=6m&indicators=sma50,rsi14", M.ChartResponse)
    n = len(d["bars"]["t"])
    assert all(len(d["bars"][k]) == n for k in "ohlcv") and all(len(v) == n for v in d["indicators"].values())
    assert d["indicators"]["sma50"][0] is not None             # computed on full history, then sliced
    w = get_ok(client, "/api/chart/IGIL?tf=1w&range=1y", M.ChartResponse)
    from datetime import date
    days = [date.fromisoformat(t) for t in w["bars"]["t"]]
    assert all(x.weekday() <= 4 for x in days)                 # last trading date of each week
    idx = get_ok(client, "/api/chart/NIFTY50?range=3m", M.ChartResponse)
    assert idx["kind"] == "index" and set(idx["bars"]["v"]) == {0.0}
    assert all(m["t"] in d["bars"]["t"] for m in d["markers"])


def test_overview_details(mclient, env):
    o = get_ok(mclient, "/api/overview", M.OverviewResponse)
    order = {"danger": 0, "warn": 1, "info": 2, "good": 3}
    assert [order[a["severity"]] for a in o["alerts"]] == sorted(order[a["severity"]] for a in o["alerts"])
    assert len({a["id"] for a in o["alerts"]}) == len(o["alerts"])
    assert any(a["category"] == "bias" for a in o["alerts"])
    assert set(o["empty_reasons"]) == {"intraday", "swing", "longterm"}
    assert all(len(v) <= 5 for v in o["movers"].values())
    assert len(o["strategy_pulse"]) <= 6
    assert o["market"]["nifty_sma200"] and o["market"]["nifty_vs_sma200_pct"] is not None
    assert o["changes"]["items"] == []                        # no earlier data_date in the fixture
    # a previous scan with an older data_date -> "since last scan" diff
    lt = latest_fixture(env)
    prev = json.loads(json.dumps(lt))
    prev["data_date"], prev["generated_at"] = "2026-10-21", "2026-10-21T19:15:00+05:30"
    prev["strategies"][0]["status"] = "mixed"
    prev["strategies"][0]["positions"] = []
    prev["market"]["regime_up"] = True
    for s in prev["strategies"]:
        s["actions"] = []
    (env / "data" / "results" / "scan_20261021_1915.json").write_text(json.dumps(prev, indent=1), encoding="utf-8")
    caches.clear_all()
    o = get_ok(mclient, "/api/overview", M.OverviewResponse)
    kinds = {c["kind"] for c in o["changes"]["items"]}
    assert {"status", "regime", "position_opened"} <= kinds
    assert o["changes"]["since_data_date"] == "2026-10-21"
    assert any(a["category"] == "market" and "regime" in a["id"] for a in o["alerts"])


def test_results_days_recomputed_from_today(client):
    r = get_ok(client, "/api/market/results?days=60", M.ResultsResponse)
    from web.api.util import today_ist
    from datetime import date
    for e in r["events"]:
        assert e["days_until"] == (date.fromisoformat(e["date"]) - today_ist()).days >= 0


def test_intraday_is_honest(client):
    d = get_ok(client, "/api/intraday", M.IntradayResponse)
    assert d["available"] and d["data"]["interval"] == "5m"
    assert d["sebi"]["points"] and "square_off" in d["rules"]
    losers = [s for s in d["strategies"] if (s["metrics"]["return_pct"] or 0) <= 0]
    if len(losers) == len(d["strategies"]):
        assert d["summary"].startswith(f"All {len(losers)} intraday strategies lost money after costs")


def test_intraday_run_starts_background_job(mclient, env, monkeypatch):
    from web.api.services import intraday_job

    class FakePopen:
        pid = 77

        def __init__(self, args, **kw):
            self.args = args

        def poll(self):
            return None
    monkeypatch.setattr(intraday_job.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(intraday_job, "_proc", {"popen": None})
    r = mclient.post("/api/intraday/run", json={"update": False}, headers=GUARD)
    assert r.status_code == 202 and r.json()["run"]["running"] and r.json()["run"]["pid"] == 77
    _err(mclient.post("/api/intraday/run", json={}, headers=GUARD), 409, "SCAN_BUSY")


def test_intraday_job_from_before_a_restart_still_counts(mclient, env, monkeypatch):
    from scanner.lock import _try_lock, _unlock
    from web.api.paths import P
    from web.api.services import intraday_job
    monkeypatch.setattr(intraday_job, "_proc", {"popen": None})          # a freshly started API process
    P.intraday_status.write_text(json.dumps({"state": "running", "message": "Testing", "started": 1792734489.0,
                                             "pid": 99}), encoding="utf-8")
    with open(P.intraday_lock, "a+") as fh:                                 # the job still holds its lock
        assert _try_lock(fh)
        try:
            run = intraday_job.run_status()
            assert run["state"] == "running" and run["running"] and run["pid"] == 99
            _err(mclient.post("/api/intraday/run", json={}, headers=GUARD), 409, "SCAN_BUSY")
            assert P.intraday_status.exists()                               # its status file is left alone
        finally:
            _unlock(fh)
    run = intraday_job.run_status()                                         # lock released, file says running
    assert run["state"] == "failed" and not run["running"]


def test_costs_preview_matches_cost_model(client):
    from scanner.costs import CostModel
    p = get_ok(client, "/api/costs/preview?value=33333", M.CostPreview)
    cm = CostModel()
    assert p["round_trip_pct"] == pytest.approx(cm.round_trip_pct(33333), abs=1e-3)
    assert p["buy"]["total"] + p["sell"]["total"] == pytest.approx(cm.round_trip_pct(33333) * 333.33, rel=1e-3)
    assert p["sell"]["dp"] == 14.75 and p["buy"]["dp"] == 0 and p["sell"]["stamp"] == 0


def test_trades_page_filters_and_stats(client):
    t = get_ok(client, "/api/strategies/momentum/trades?outcome=win&page_size=10&sort=-ret_pct", M.TradesPage)
    assert t["source"] == "artifact" and t["total"] > 10 and len(t["rows"]) == 10
    assert all(r["ret_pct"] > 0 for r in t["rows"])
    assert [r["ret_pct"] for r in t["rows"]] == sorted((r["ret_pct"] for r in t["rows"]), reverse=True)
    assert sum(b["count"] for b in t["histogram"]) == t["total"] and t["stats"]["win_rate"] == 100.0


def test_screener_preset_and_sparkline_limits(client):
    s = get_ok(client, "/api/screener?preset=momentum", M.ScreenerResponse)
    scores = [r["momentum_score"] for r in s["rows"]]
    assert scores == sorted(scores, reverse=True) and all(r["above_sma200"] for r in s["rows"])
    sp = get_ok(client, "/api/sparklines?symbols=IGIL,NOPE&days=20", M.SparklinesResponse)
    assert list(sp["series"]) == ["IGIL"] and len(sp["series"]["IGIL"]) == 20


def test_screener_results_within_filter(client):
    """Missing results dates are NaN in a pandas-3 string column: the filter must not compare NaN with a date."""
    from datetime import date
    from web.api.util import today_ist
    allr = get_ok(client, "/api/screener?preset=all&min_turnover_cr=0", M.ScreenerResponse)["rows"]
    s = get_ok(client, "/api/screener?preset=all&min_turnover_cr=0&results_within=30", M.ScreenerResponse)
    assert s["rows"] and len(s["rows"]) < len(allr)                  # some symbols report, most do not
    for r in s["rows"]:
        assert r["results_on"] and 0 <= (date.fromisoformat(r["results_on"]) - today_ist()).days <= 30


def test_yearly_returns_are_calendar_years_like_the_monthly_totals(client):
    """A year runs from the previous year-end close (not the year's first close), so the yearly table and the
    monthly table's year total agree, for the strategy and for each benchmark."""
    from web.api.services import data
    d = get_ok(client, "/api/strategies/momentum", M.StrategyDetail)
    totals = {r["year"]: r["total"] for r in d["monthly"]}
    assert len(d["yearly"]) >= 3
    for y in d["yearly"]:
        assert y["strategy"] == pytest.approx(totals[y["year"]], abs=0.051)
    c = data.curves()
    eq = c["momentum"].dropna()
    n500 = c["NIFTY 500"].reindex(eq.index).ffill()
    full = [y for y in d["yearly"] if not y["partial"] and y["year"] > d["yearly"][0]["year"]]
    assert full
    y = full[0]["year"]
    want = (n500[n500.index.year == y].iloc[-1] / n500[n500.index.year == y - 1].iloc[-1] - 1) * 100
    assert full[0]["nifty500"] == pytest.approx(want, abs=0.051)


def test_lots_of_one_symbol_are_summed(mclient, env):
    """Two holdings.csv rows of one symbol are two lots: a SELL of it sizes on the total, and rows added after
    the scan get their P&L like the totals do."""
    pos = _with_sell(env)
    sym = pos["symbol"]
    (env / "holdings.csv").write_text("symbol,qty,buy_price,buy_date,stop_loss_pct,target_pct\n"
                                      f"{sym},100,70,,,\n{sym},20,80,,,\n", encoding="utf-8")
    caches.clear_all()
    body = get_ok(mclient, "/api/signals", M.SignalsResponse)
    o = next(o for g in body["groups"] for o in g["orders"] if o["action"] == "SELL")
    assert (o["qty"], o["qty_basis"], o["you_hold_qty"]) == (120, "your_holding", 120)
    h = get_ok(mclient, "/api/holdings", M.HoldingsResponse)
    rows = [r for r in h["rows"] if r["symbol"] == sym]
    assert len(rows) == 2 and all(r["price"] is not None for r in rows)
    for r in rows:
        assert r["pnl_pct"] == pytest.approx((r["price"] / r["buy_price"] - 1) * 100, abs=0.01)
        assert r["pnl_amount"] == pytest.approx((r["price"] - r["buy_price"]) * r["qty"], abs=0.01)
    assert h["totals"]["pnl"] == pytest.approx(sum(r["pnl_amount"] for r in rows), abs=0.05)


def test_mutations_refuse_a_foreign_origin(mclient, env):
    bad = {"rows": "not-a-list"}           # past the guards this is a 422, so nothing is ever written
    for origin in ("http://evil.example.com", "null", "http://127.0.0.1.nip.io:8600", "file://"):
        _err(mclient.put("/api/holdings", json=bad, headers={**GUARD, "Origin": origin}), 403, "CSRF")
    for origin in ("http://127.0.0.1:8600", "http://localhost:5173", None):
        hdr = {**GUARD, **({"Origin": origin} if origin else {})}
        _err(mclient.put("/api/holdings", json=bad, headers=hdr), 422, "VALIDATION")
    assert mclient.get("/api/health", headers={"Origin": "http://evil.example.com"}).status_code == 200


def test_wrong_method_on_a_known_path_is_405(client):
    e = _err(client.delete("/api/holdings", headers=GUARD), 405, "VALIDATION")
    assert e["details"] == {"allowed": ["GET", "PUT"]}
    _err(client.post("/api/strategies/momentum", headers=GUARD), 405, "VALIDATION")
    _err(client.delete("/api/nope", headers=GUARD), 404, "NOT_FOUND")


# ------------------------------------------------------------------ optional: the real data folder
REAL = settings.DATA_DIR / "results" / "latest.json"


@pytest.mark.skipif(not REAL.exists(), reason="no real scan in data/")
def test_real_data_breadth_matches_scan():
    """On the real store the last breadth point equals latest.market.breadth_50 (same symbols + ETF rule)."""
    configure(settings.ROOT, settings.DATA_DIR)
    caches.clear_all()
    lt = json.loads(REAL.read_text(encoding="utf-8"))
    if lt.get("live"):
        pytest.skip("live scan: its breadth includes today's forming candle")
    c = TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    b = c.get("/api/market/breadth?range=1y").json()
    if b["source_date"] != lt["data_date"]:
        pytest.skip("store is newer/older than the scan")
    assert b["breadth_50"][-1] == pytest.approx(lt["market"]["breadth_50"], abs=0.15)


def test_openapi_file_is_current():
    """web/api/openapi.json (the UI's schema source) must match the models: regenerate with
    `python -m web.api.main --openapi` after changing web/api/models."""
    from web.api.main import OPENAPI_FILE, create_app
    assert OPENAPI_FILE.exists(), "run: python -m web.api.main --openapi"
    committed = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(create_app(warm=False).openapi())), \
        "web/api/openapi.json is out of date: run python -m web.api.main --openapi"
