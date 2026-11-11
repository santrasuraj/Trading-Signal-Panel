"""Live setups (scanner/intraday/setups.py) and the trade journal (web/api/services/journal_svc.py). Synthetic bars and
trades in a temporary folder: nothing real is read or written."""
import json

import numpy as np
import pandas as pd
import pytest

from scanner.intraday import setups
from web.api.paths import P
from web.api.services import data, journal_svc, replay_svc


def _bars(closes, start="2026-11-12 09:15", step=5, sym="AAA", vol=None, opens=None, highs=None, lows=None):
    n = len(closes)
    ts = pd.date_range(start, periods=n, freq=f"{step}min")
    c = np.asarray(closes, float)
    o = np.asarray(opens if opens is not None else np.r_[c[0], c[:-1]], float)
    h = np.asarray(highs if highs is not None else np.maximum(o, c) + 0.1, float)
    lo = np.asarray(lows if lows is not None else np.minimum(o, c) - 0.1, float)
    v = np.asarray(vol if vol is not None else np.full(n, 10_000.0), float)
    return pd.DataFrame({"ts": ts, "symbol": sym, "open": o, "high": h, "low": lo, "close": c, "volume": v, "flags": 0})


def test_gap_opening_range_and_fresh_high():
    closes = [103, 103.5, 103.2] + [103.4] * 6 + [104.5]          # 15-minute range, flat for 30 min, then a break
    b = _bars(closes, opens=[103.0] + closes[:-1])
    ev = setups.detect(b, 5, {"AAA": {"close": 100.0, "high_52w": 104.0, "low_52w": 80.0}})
    kinds = {e["kind"] for e in ev}
    assert {"gap_up", "orb_up", "new_high", "high_52w"} <= kinds
    gap = next(e for e in ev if e["kind"] == "gap_up")
    assert gap["time"].endswith("09:15:00") and gap["change_pct"] == 3.0
    assert ev[0]["time"] >= ev[-1]["time"]                          # newest first


def test_volume_spike_needs_size_and_value():
    vol = [50_000] + [10_000] * 8 + [80_000]
    ev = setups.detect(_bars([500.0] * 10, vol=vol), 5, {})
    assert [e["kind"] for e in ev] == ["volume_spike"]
    small = setups.detect(_bars([5.0] * 10, vol=vol), 5, {})       # Rs 4 lakh in the bar: below the floor
    assert small == []


def test_vwap_cross_after_time_below():
    closes = [100.0] * 3 + [99.0] * 7 + [101.0]
    ev = setups.detect(_bars(closes), 5, {})
    assert any(e["kind"] == "vwap_up" for e in ev)


@pytest.fixture
def jdir(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "data", tmp_path)
    monkeypatch.setattr(data, "config", lambda: {"costs": {}})
    monkeypatch.setattr(data, "store", lambda: {})
    (tmp_path / "sim_account.json").write_text(json.dumps({"cash": 1, "start_cash": 1, "positions": {}, "orders": [], "charges": 0,
        "trades": [{"symbol": "TCS", "side": "LONG", "qty": 10, "entry": 100, "exit": 110, "pnl": 100, "charges": 5,
                    "reason": "target", "opened": "2026-11-10T10:05:00", "closed": "2026-11-11T11:00:00", "product": "CNC"},
                   {"symbol": "INFY", "side": "LONG", "qty": 10, "entry": 100, "exit": 95, "pnl": -50, "charges": 5,
                    "reason": "stop", "opened": "2026-11-10T14:05:00", "closed": "2026-11-10T15:00:00", "product": "INTRADAY"}]}))
    from scanner import fills
    monkeypatch.setattr(fills, "read", lambda *a, **k: [])
    monkeypatch.setattr(replay_svc, "log_rows", lambda: [])
    return tmp_path


def test_journal_stats_and_notes(jdir):
    v = journal_svc.view()
    assert v["counts"]["practice"] == 2
    o = v["stats"]["overall"]
    assert o["trades"] == 2 and o["win_rate"] == 50 and o["total"] == 40 and o["profit_factor"] == pytest.approx(95 / 55, abs=0.01)
    t = next(x for x in v["trades"] if x["symbol"] == "INFY")
    journal_svc.save_note(t["id"], {"setup": "Breakout", "mistakes": ["Chased the entry"], "notes": "too late", "rating": 2})
    v = journal_svc.view()
    t = next(x for x in v["trades"] if x["symbol"] == "INFY")
    assert t["setup"] == "Breakout" and t["notes"] == "too late"
    assert v["stats"]["by_mistake"][0] == {**v["stats"]["by_mistake"][0], "key": "Chased the entry", "total": -55}
    by_hour = {r["key"]: r["trades"] for r in v["stats"]["by_hour"]}
    assert by_hour == {"10:00": 1, "14:00": 1}
    from web.api.errors import ApiException
    with pytest.raises(ApiException):
        journal_svc.save_note("0" * 12, {"notes": "x"})
    with pytest.raises(ApiException):
        journal_svc.save_note(t["id"], {"image": "javascript:alert(1)"})
