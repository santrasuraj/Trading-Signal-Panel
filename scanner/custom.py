"""Your own strategies, written as a spec (plain English -> Claude -> this spec, or the builder form) and tested like the
built-in ones: entries from scan rules (scanner/scans.py FIELDS), exits by stop / target / trailing stop / holding days
or exit rules, simulated by the same engine (scanner/engine.py) on the same 8-year survivorship-free top 500 with the
same costs, slippage and tax, judged by the same "working" test.

    spec = {"name": ..., "entry": {"match": "all"|"any", "rules": [scan rules]},
            "exit": {"stop_pct": 8, "target_pct": None, "trail_pct": None, "max_days": None,
                     "match": "any", "rules": [scan rules]},          # exit rules optional
            "max_positions": 10, "priority": "rs_rating" | None}     # which signals first when slots are short

No code is ever generated or run: a spec is data, checked field by field.

optimise() tries a small grid of exit settings and keeps itself honest with a walk-forward: each year the settings are
chosen on the years before it only, and the result is the chain of those unseen years, next to the in-sample best and a
deflated Sharpe ratio for the number of settings tried.
"""
from __future__ import annotations

import itertools
import json
import math
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from . import scans

MAX_POSITIONS = (1, 50)
GRID = {"stop_pct": (5.0, 8.0, 12.0), "target_pct": (None, 15.0, 30.0), "max_days": (None, 20, 60)}
FIRST_TEST_YEARS = 3        # the walk-forward chooses on at least this many years before its first unseen year


def _num(v, lo, hi, name):
    if v in (None, "", 0):
        return None
    v = float(v)
    if not (lo <= v <= hi):
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}.")
    return v


def validate(spec: dict) -> dict:
    name = str(spec.get("name") or "My strategy").strip()[:60]
    entry = scans.validate({"name": name, "match": (spec.get("entry") or {}).get("match", "all"), "direction": "long",
                            "rules": (spec.get("entry") or {}).get("rules") or []})
    ex = spec.get("exit") or {}
    exit_rules = ex.get("rules") or []
    exit_scan = scans.validate({"name": name, "match": ex.get("match", "any"), "direction": "long",
                                "rules": exit_rules}) if exit_rules else None
    out_exit = {"stop_pct": _num(ex.get("stop_pct"), 1, 50, "Stop"), "target_pct": _num(ex.get("target_pct"), 2, 500, "Target"),
                "trail_pct": _num(ex.get("trail_pct"), 1, 50, "Trailing stop"),
                "max_days": int(_num(ex.get("max_days"), 1, 750, "Holding days") or 0) or None,
                "match": exit_scan["match"] if exit_scan else "any", "rules": exit_scan["rules"] if exit_scan else []}
    if not any(out_exit[k] for k in ("stop_pct", "target_pct", "trail_pct", "max_days")) and not out_exit["rules"]:
        raise ValueError("Give at least one way out: a stop, a target, a trailing stop, a holding limit or an exit rule.")
    mp = int(spec.get("max_positions") or 10)
    if not MAX_POSITIONS[0] <= mp <= MAX_POSITIONS[1]:
        raise ValueError(f"Positions between {MAX_POSITIONS[0]} and {MAX_POSITIONS[1]}.")
    prio = spec.get("priority") or None
    if prio and prio not in scans.FIELDS:
        raise ValueError(f"Unknown ranking field {prio!r}.")
    return {"name": name, "entry": {"match": entry["match"], "rules": entry["rules"]}, "exit": out_exit,
            "max_positions": mp, "priority": prio}


def describe(spec: dict) -> dict:
    join = lambda m: " AND " if m == "all" else " OR "  # noqa: E731
    ex = spec["exit"]
    outs = [f"stop {ex['stop_pct']:g}% below the fill" if ex.get("stop_pct") else None,
            f"target {ex['target_pct']:g}% above" if ex.get("target_pct") else None,
            f"trailing stop {ex['trail_pct']:g}%" if ex.get("trail_pct") else None,
            f"after {ex['max_days']} trading days" if ex.get("max_days") else None]
    if ex.get("rules"):
        outs.append("when " + join(ex["match"]).join(scans.describe_rule(r) for r in ex["rules"]))
    return {"entry": join(spec["entry"]["match"]).join(scans.describe_rule(r) for r in spec["entry"]["rules"]),
            "exit": "; ".join(x for x in outs if x),
            "sizing": f"up to {spec['max_positions']} positions, equal money each"
                      + (f"; strongest {scans.FIELDS[spec['priority']].label} first" if spec.get("priority") else "")}


def to_strategy(spec: dict, ctx, overrides: dict | None = None):
    """The engine strategy for a spec on scans.Ctx `ctx` (masks computed once and reused across optimiser runs)."""
    from .engine import EventStrategy
    ex = {**spec["exit"], **(overrides or {})}
    entry = scans.evaluate({"match": spec["entry"]["match"], "rules": spec["entry"]["rules"]}, ctx)
    exit_m = scans.evaluate({"match": ex["match"], "rules": ex["rules"]}, ctx) if ex.get("rules") else None
    prio = ctx.get(spec["priority"]) if spec.get("priority") else None
    return EventStrategy(
        key="custom", name=spec["name"], description=describe(spec)["entry"],
        entries=lambda f, m=entry: m, exit_signal=(lambda f, m=exit_m: m) if exit_m is not None else None,
        priority=(lambda f, m=prio: m) if prio is not None else None,
        stop_pct=ex.get("stop_pct"), target_pct=ex.get("target_pct"), trail_pct=ex.get("trail_pct"),
        max_hold=ex.get("max_days"), max_positions=spec["max_positions"], horizon="swing", evidence="EXPERIMENTAL")


class Setup:
    """What every test of a custom strategy runs on: the point-in-time panel, its scan context, the tradable mask,
    the benchmarks and the cost / tax models (built once per call; the scan context's fields are cached)."""

    def __init__(self, store_frames: dict, cfg: dict):
        from . import pit
        from .costs import CostModel, TaxModel
        from .engine import equal_weight_index
        from .panel import Factors, panel_from_wide
        from .providers import INDEX_N500
        from .strategies import tradable_mask
        data = pit.load()
        if data is None:
            raise RuntimeError("The survivorship-free universe is not built yet: run 4_build_universe.bat once.")
        self.panel = panel_from_wide(pit.backtest_frames(data, store_frames), list(data.members), universe=data.universe)
        extra = {"deliv_pct": data.frames["deliv_pct"]} if "deliv_pct" in data.frames else None
        self.ctx = scans.Ctx(self.panel, extra)
        self.f = Factors(self.panel)
        flt = cfg.get("filters") or {}
        self.trad = tradable_mask(self.f, float(flt.get("min_price", 50)), float(flt.get("min_turnover_cr", 5)),
                                  price=pit.as_traded(data, self.panel.close))
        self.ew = equal_weight_index(self.f, self.trad)
        self.n500 = store_frames["close"][INDEX_N500].reindex(self.panel.dates) if INDEX_N500 in store_frames["close"].columns else None
        self.costs = CostModel.from_config(cfg.get("costs"))
        self.tax = TaxModel.from_config(cfg.get("tax"))
        acct = cfg.get("account") or {}
        self.capital = float(acct.get("capital", 500000))
        self.min_position = float(acct.get("min_position", 0))

    def run(self, strat):
        from .engine import simulate
        return simulate(strat, self.f, self.costs, self.trad, capital=self.capital, min_position=self.min_position)


def _cagr(eq: pd.Series) -> float | None:
    eq = eq.dropna()
    if len(eq) < 30 or eq.iloc[0] <= 0:
        return None
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0.2 else None


def backtest(spec: dict, setup: Setup) -> dict:
    """The spec through the same tests as a built-in strategy."""
    from .engine import evaluate, working_status
    t0 = time.monotonic()
    spec = validate(spec)
    res = setup.run(to_strategy(spec, setup.ctx))
    m = evaluate(res, setup.panel.index_close, setup.ew, tax=setup.tax, n500_benchmark=setup.n500,
                 stt_pct=setup.costs.stt_pct)
    status, why = working_status(m)
    eq = res.equity.dropna()
    cut = eq.index[int(len(eq) * 0.7)] if len(eq) > 10 else eq.index[-1]
    yearly = {str(y): round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1) for y, g in eq.groupby(eq.index.year) if len(g) > 5}
    return {"spec": spec, "text": describe(spec), "status": status, "status_reason": why,
            "metrics": json.loads(json.dumps(m["full"], default=lambda x: None if isinstance(x, float) and not math.isfinite(x) else str(x))),
            "windows": {k: {kk: m[k].get(kk) for kk in ("return_pct", "cagr_pct")} for k in ("12m", "6m", "3m") if k in m},
            "split": {"in_sample_cagr_pct": _cagr(eq.loc[:cut]), "out_of_sample_cagr_pct": _cagr(eq.loc[cut:]),
                      "cut": cut.date().isoformat()},
            "yearly": yearly, "trades": len(res.trades),
            "curve": [[d.date().isoformat(), round(float(v), 4)] for d, v in (eq / eq.iloc[0]).iloc[::5].items()],
            "elapsed_s": round(time.monotonic() - t0, 1)}


def _sharpe(r: np.ndarray) -> float:
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0


def optimise(spec: dict, setup: Setup, grid: dict | None = None, progress=None) -> dict:
    """Walk-forward: every exit setting of the grid is simulated once; each year the setting with the best Sharpe
    ratio on the years before it is used for that year. Returns the unseen-years result next to the in-sample best."""
    spec = validate(spec)
    grid = grid or GRID
    keys = list(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]
    curves = {}
    for i, c in enumerate(combos, 1):
        res = setup.run(to_strategy(spec, setup.ctx, c))
        curves[i - 1] = res.equity.dropna()
        if progress:
            progress(i, len(combos))
    rets = pd.DataFrame({k: v.pct_change() for k, v in curves.items()}).dropna(how="all").fillna(0.0)
    years = sorted(set(rets.index.year))
    first = years[0] + FIRST_TEST_YEARS
    chain, picks = [], []
    for y in [y for y in years if y >= first]:
        past = rets[rets.index.year < y]
        best = max(range(len(combos)), key=lambda k: _sharpe(past[k].to_numpy()))
        picks.append({"year": y, "settings": combos[best]})
        chain.append(rets.loc[rets.index.year == y, best])
    oos = pd.concat(chain) if chain else pd.Series(dtype=float)
    oos_curve = (1 + oos).cumprod()
    tested = rets[rets.index.year >= first]
    full_best = max(range(len(combos)), key=lambda k: _sharpe(tested[k].to_numpy()))
    hind = (1 + tested[full_best]).cumprod()
    base = next((k for k, c in enumerate(combos) if all(c[x] == spec["exit"].get(x) for x in keys)), None)
    trial_srs = [_sharpe(tested[k].to_numpy()) / np.sqrt(252) for k in range(len(combos))]   # daily, as deflated_sharpe expects
    from web.api.services.robustness import deflated_sharpe
    ds = deflated_sharpe(oos.to_numpy(), trial_srs) if len(oos) > 60 else None
    return {"spec": spec, "combos": len(combos), "first_unseen_year": first,
            "walk_forward_cagr_pct": _cagr(oos_curve), "hindsight_best_cagr_pct": _cagr(hind),
            "hindsight_best": combos[full_best], "your_settings_cagr_pct": _cagr((1 + tested[base]).cumprod()) if base is not None else None,
            "picks": picks, "deflated_sharpe": ds,
            "curve": [[d.date().isoformat(), round(float(v), 4)] for d, v in oos_curve.iloc[::5].items()],
            "note": ("Each year uses the exit settings that did best on the years before it only; the walk-forward line "
                     "is those unseen years chained. The hindsight best is what picking with all the data would have "
                     "shown: the gap between the two is the optimism that tuning adds.")}


# ---- saved strategies ------------------------------------------------------------------------------------------

def _file() -> Path:
    from .settings import DATA_DIR
    return Path(DATA_DIR) / "custom_strategies.json"


def saved(path: Path | None = None) -> list[dict]:
    try:
        return json.loads((path or _file()).read_text(encoding="utf-8")).get("strategies") or []
    except (OSError, ValueError):
        return []


def save(spec: dict, sid: str | None = None, path: Path | None = None, result: dict | None = None) -> dict:
    spec = validate(spec)
    items = saved(path)
    sid = sid or uuid.uuid4().hex[:10]
    row = {"id": sid, **spec, "saved": pd.Timestamp.now().isoformat(timespec="seconds"),
           "last_test": {k: (result or {}).get(k) for k in ("status", "status_reason")} if result else None}
    items = [x for x in items if x.get("id") != sid] + [row]
    p = path or _file()
    p.write_text(json.dumps({"strategies": items[-50:]}, indent=1), encoding="utf-8")
    return row


def delete(sid: str, path: Path | None = None) -> None:
    p = path or _file()
    items = [x for x in saved(path) if x.get("id") != sid]
    p.write_text(json.dumps({"strategies": items}, indent=1), encoding="utf-8")
