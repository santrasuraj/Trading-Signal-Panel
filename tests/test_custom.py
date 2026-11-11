"""Your own strategies (scanner/custom.py, web/api/services/builder_svc.py) and dated charges (scanner/costs.py).
Synthetic data and a fake simulator: no point-in-time data, no Claude call."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scanner import custom
from scanner.costs import CostModel
from web.api.errors import ApiException
from web.api.services import builder_svc

SPEC = {"name": "Breakout", "entry": {"match": "all", "rules": [{"left": "close", "op": ">", "right": {"field": "high_52w_prev"}}]},
        "exit": {"stop_pct": 8, "trail_pct": 15}, "max_positions": 10, "priority": "rs_rating"}


def test_spec_is_validated_and_described():
    s = custom.validate(SPEC)
    assert s["exit"]["stop_pct"] == 8 and s["exit"]["target_pct"] is None and s["max_positions"] == 10
    d = custom.describe(s)
    assert "52-week high" in d["entry"] and "stop 8%" in d["exit"] and "trailing stop 15%" in d["exit"]
    with pytest.raises(ValueError, match="way out"):
        custom.validate({**SPEC, "exit": {}})
    with pytest.raises(ValueError):
        custom.validate({**SPEC, "priority": "not_a_field"})
    with pytest.raises(ValueError):
        custom.validate({**SPEC, "exit": {"stop_pct": 90}})


def test_walk_forward_chooses_each_year_on_the_past_only(monkeypatch, tmp_path):
    idx = pd.bdate_range("2018-01-01", "2025-12-31")
    yr = idx.year.to_numpy()

    def curve(c):
        # setting A (stop 5) is best until 2019 and bad after; setting B (stop 12) the other way round
        good = (yr <= 2019) if c["stop_pct"] == 5.0 else (yr > 2019) if c["stop_pct"] == 12.0 else np.zeros(len(yr), bool)
        r = np.where(good, 0.001, -0.0002) + np.random.default_rng(int(c["stop_pct"])).normal(0, 0.002, len(yr))
        return SimpleNamespace(equity=pd.Series(np.cumprod(1 + r), index=idx))
    monkeypatch.setattr(custom, "to_strategy", lambda spec, ctx, over=None: over)
    setup = SimpleNamespace(ctx=None, run=curve)
    out = custom.optimise(SPEC, setup, grid={"stop_pct": (5.0, 8.0, 12.0)})
    assert out["combos"] == 3 and out["first_unseen_year"] == 2021
    picks = {p["year"]: p["settings"]["stop_pct"] for p in out["picks"]}
    assert picks[2021] == 5.0                                  # chosen on 2018-2020, when A was best
    assert picks[2025] == 12.0                                 # by then B's record has overtaken
    assert out["hindsight_best_cagr_pct"] >= out["walk_forward_cagr_pct"]   # tuning with hindsight flatters


def test_saved_strategies_round_trip(tmp_path):
    p = tmp_path / "custom.json"
    row = custom.save(SPEC, path=p, result={"status": "working", "status_reason": "x"})
    assert custom.saved(p)[0]["id"] == row["id"] and row["last_test"]["status"] == "working"
    custom.delete(row["id"], p)
    assert custom.saved(p) == []


def test_plain_english_answer_becomes_a_spec():
    rule = {"left": "rsi14", "op": "<", "right": {"kind": "value", "value": 30, "field": "close", "mult": 1}}
    d = {"name": "Dip buy", "entry_match": "all", "entry_rules": [rule], "stop_pct": None, "target_pct": 10, "trail_pct": None,
         "max_days": 15, "exit_match": "any", "exit_rules": [], "max_positions": 5, "priority": None,
         "explanation": "Buys oversold stocks.", "unsupported": "news"}
    out = builder_svc.to_spec(d)
    assert out["spec"]["entry"]["rules"][0]["right"] == {"value": 30} and out["spec"]["exit"]["max_days"] == 15
    assert out["unsupported"] == "news"
    with pytest.raises(ApiException):
        builder_svc.to_spec({**d, "target_pct": None, "max_days": None})          # no way out at all


def test_charges_are_dated():
    cm = CostModel()
    assert cm.on("2019-06-03").sebi_pct == 0.00015 and cm.on("2019-06-03").stamp_buy_pct == 0.01
    assert cm.on("2023-06-01").exchange_pct == 0.00325 and cm.on("2025-06-02").exchange_pct == 0.00297
    assert cm.on("2026-06-01") is cm                                             # today's rates
    assert CostModel(dated=0).on("2019-06-03").sebi_pct == cm.sebi_pct
