"""Market-wide seasonality (scanner/seasonal.py, web/api/services/seasonal_svc.py, GET /api/seasonal): monthly and
season returns from month-end closes, the per-stock record against the bench, the chance check, the walk-forward test
(earlier years only, point-in-time members, after costs) and the sector grid. Synthetic prices only."""
import numpy as np
import pandas as pd
import pytest

from scanner import seasonal as sz

BENCH = "NIFTY500"


def closes(monthly: dict[str, list[float]], start="2017-12-29") -> pd.DataFrame:
    """Daily closes (business days) built from month-by-month % moves, flat inside each month except its last day."""
    n = len(next(iter(monthly.values())))
    months = pd.period_range(pd.Period(start, "M") + 1, periods=n, freq="M")
    days = pd.bdate_range(start, months[-1].end_time.normalize())
    out = {}
    for sym, moves in monthly.items():
        level, s = 100.0, pd.Series(np.nan, index=days)
        s.iloc[0] = level
        for m, r in zip(months, moves):
            last = days[(days.to_period("M") == m)][-1]
            level *= 1 + r / 100
            s.loc[last] = level
        out[sym] = s.ffill()
    return pd.DataFrame(out)


def pattern(n_years=8, nov=0.0, other=0.0, noise=None, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for _y in range(n_years):
        for m in range(1, 13):
            base = nov if m == 11 else other
            out.append(base + (rng.normal(0, noise) if noise else 0.0))
    return out


def test_monthly_returns_come_from_month_end_closes_and_skip_the_month_in_progress():
    c = closes({"A": [10.0, -5.0, 2.0]})
    r = sz.monthly_returns(c).dropna()
    assert list(r.index.astype(str)) == ["2018-01", "2018-02", "2018-03"]
    assert r["A"].tolist() == pytest.approx([10.0, -5.0, 2.0])
    part = c.loc[:"2018-03-15"]                                   # March not over: left out
    assert list(sz.monthly_returns(part).dropna().index.astype(str)) == ["2018-01", "2018-02"]


def test_a_season_compounds_its_months_and_needs_all_of_them():
    mret = pd.DataFrame({"A": [10.0, 10.0, np.nan, 5.0]},
                        index=pd.PeriodIndex(["2020-01", "2020-02", "2021-01", "2021-02"], freq="M"))
    per = sz.period_returns(mret, (1, 2))
    assert per.at[2020, "A"] == pytest.approx(21.0)               # 1.1 x 1.1
    assert np.isnan(per.at[2021, "A"])                            # January missing: no 2021 season


def test_periods_cover_every_month_once_and_seasons_stay_inside_a_year():
    seasons = [p for p in sz.period_list() if p["kind"] == "season"]
    months = sorted(m for p in seasons for m in p["months"])
    assert months == list(range(1, 13))
    assert all(list(p["months"]) == sorted(p["months"]) for p in seasons)
    assert sz.season_of(11)["key"] == "festive" and sz.find_period("3")["name"] == "March"
    assert sz.find_period("nope") is None


def test_a_steady_november_stock_is_consistent_and_a_noisy_one_is_not():
    c = closes({"STEADY": pattern(nov=6.0, noise=1.0, seed=1), "NOISY": pattern(noise=5.0, seed=2),
                BENCH: pattern(nov=1.0, noise=0.5, seed=3)})
    mret = sz.monthly_returns(c)
    per = sz.period_returns(mret, (11,))
    st = sz.stock_stats(per[["STEADY", "NOISY"]], per[BENCH]).set_index("symbol")
    assert st.at["STEADY", "n"] == 8 and st.at["STEADY", "beat_pct"] == 100.0
    assert st.at["STEADY", "excess_pct"] == pytest.approx((per["STEADY"] - per[BENCH]).mean())
    assert st.at["STEADY", "strength"] == "consistent" and st.at["STEADY", "t"] > 2
    assert st.at["NOISY", "strength"] in ("noise", "lean")
    assert set(st.at["STEADY", "years"]) == set(range(2018, 2026))


def test_strength_needs_enough_years_and_direction():
    assert sz.strength(8, 3.0, 90.0, +1) == "consistent"
    assert sz.strength(8, -3.0, 10.0, -1) == "consistent"          # a steady faller
    assert sz.strength(5, 3.0, 90.0, +1) == "noise"                # too few years
    assert sz.strength(8, 1.6, 60.0, +1) == "lean"
    assert sz.strength(8, 0.4, 55.0, +1) == "noise"


def test_vectorised_counts_match_the_per_stock_labels():
    rng = np.random.default_rng(5)
    data = {f"S{i}": pattern(nov=rng.choice([4.0, -4.0, 0.0]), noise=2.5, seed=i) for i in range(40)}
    data[BENCH] = pattern(noise=1.0, seed=99)
    mret = sz.monthly_returns(closes(data))
    per = sz.period_returns(mret, (11,))
    st = sz.stock_stats(per.drop(columns=[BENCH]), per[BENCH])
    c = st[st["strength"] == "consistent"]
    assert sz.consistent_counts(mret, BENCH, (11,)) == (int((c["excess_pct"] > 0).sum()), int((c["excess_pct"] < 0).sum()))


def test_chance_count_is_near_zero_for_pure_noise_and_shuffling_hides_a_real_pattern():
    noise = {f"S{i}": pattern(noise=3.0, seed=i) for i in range(60)}
    noise[BENCH] = pattern(noise=1.0, seed=100)
    mret = sz.monthly_returns(closes(noise))
    ch = sz.chance_counts(mret, BENCH, (11,), n_perm=10)
    assert ch["bullish"] < 5 and ch["bearish"] < 5 and ch["permutations"] == 10
    real = {f"S{i}": pattern(nov=8.0, noise=1.0, seed=i) for i in range(30)}
    real[BENCH] = pattern(noise=0.5, seed=101)
    mret2 = sz.monthly_returns(closes(real))
    assert sz.consistent_counts(mret2, BENCH, (11,))[0] == 30         # all 30 really rise in November
    assert sz.chance_counts(mret2, BENCH, (11,), n_perm=10)["bullish"] < 15   # shuffled, most of it is gone
    assert sz.chance_counts(mret2, BENCH, (11,), n_perm=10) == sz.chance_counts(mret2, BENCH, (11,), n_perm=10)  # seeded


def test_walk_forward_uses_earlier_years_only_and_members_at_the_start():
    rng = np.random.default_rng(11)
    data = {f"S{i}": pattern(noise=2.0, seed=i) for i in range(30)}
    data["WIN"] = pattern(nov=10.0, noise=0.5, seed=200)                # always strong in November
    data["OUT"] = pattern(nov=12.0, noise=0.5, seed=201)                # strong too, but never a member
    data[BENCH] = pattern(noise=0.5, seed=202)
    mret = sz.monthly_returns(closes(data))
    member = pd.DataFrame(True, index=mret.index, columns=[c for c in mret.columns if c != BENCH])
    member["OUT"] = False
    res = sz.walk_forward(mret, member, BENCH, (11,), cost_pct=0.5, top_n=5, train_min=4)
    assert [r["year"] for r in res] == [2022, 2023, 2024, 2025]          # 4 earlier Novembers needed (2018-2021)
    assert all("WIN" in r["top"] and "OUT" not in r["top"] for r in res)
    # no look-ahead: changing a later year never changes an earlier year's picks
    later = mret.copy()
    later.loc[later.index.year == 2025, "S3"] += 50.0
    res2 = sz.walk_forward(later, member, BENCH, (11,), cost_pct=0.5, top_n=5, train_min=4)
    assert [r["top"] for r in res2[:3]] == [r["top"] for r in res[:3]]
    # costs come off the top list only
    free = sz.walk_forward(mret, member, BENCH, (11,), cost_pct=0.0, top_n=5, train_min=4)
    assert free[0]["top_excess_pct"] - res[0]["top_excess_pct"] == pytest.approx(0.5, abs=0.01)
    assert free[0]["bottom_excess_pct"] == res[0]["bottom_excess_pct"]


def test_summary_labels_follow_the_evidence():
    good = [{"top_excess_pct": 1.0 + (i % 3) * 0.1, "bottom_excess_pct": -1.0} for i in range(24)]
    assert sz.summarize(good)["status"] == "working"
    flat = [{"top_excess_pct": (1.0 if i % 2 else -0.9), "bottom_excess_pct": 0.0} for i in range(24)]
    assert sz.summarize(flat)["status"] == "mixed"
    bad = [{"top_excess_pct": -0.5, "bottom_excess_pct": 0.0} for _ in range(24)]
    assert sz.summarize(bad)["status"] == "not-working"
    assert sz.summarize(good[:5])["status"] == "untested"                # under 12 periods
    assert sz.summarize([])["status"] == "untested"


def test_sector_grid_averages_each_sectors_stocks():
    data = {"A1": pattern(nov=5.0, seed=1), "A2": pattern(nov=3.0, seed=2), "B1": pattern(nov=-2.0, seed=3),
            BENCH: pattern(seed=4)}
    mret = sz.monthly_returns(closes(data))
    grid = sz.sector_grid(mret, BENCH, {"A1": "Alpha", "A2": "Alpha", "B1": "Beta"}, min_stocks=2)
    assert [g["industry"] for g in grid] == ["Alpha"]                    # Beta has one stock: left out
    nov = next(c for c in grid[0]["cells"] if c["period"] == "11")
    assert nov["excess_pct"] == pytest.approx(4.0) and nov["beat_pct"] == 100.0 and nov["n"] == 8


# ---- the API -----------------------------------------------------------------------------------------------------
@pytest.fixture
def market(monkeypatch):
    from web.api.services import data, seasonal_svc as svc
    rng = np.random.default_rng(3)
    syms = [f"S{i}" for i in range(25)]
    cols = {s: pattern(nov=rng.choice([5.0, -5.0, 0.0]), noise=2.0, seed=i) for i, s in enumerate(syms)}
    cols[BENCH] = pattern(noise=1.0, seed=50)
    c = closes(cols)
    monkeypatch.setattr(data, "store_close", lambda: c)
    monkeypatch.setattr(data, "universe", lambda: pd.DataFrame({"symbol": syms, "company": syms,
                                                                "industry": ["Alpha"] * 12 + ["Beta"] * 13}))
    monkeypatch.setattr(data, "symbol_meta", lambda: {s: {"company": f"{s} Ltd", "industry": "Alpha" if i < 12 else "Beta"}
                                                      for i, s in enumerate(syms)})
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 500000}})
    monkeypatch.setattr(svc, "_pit_panel", lambda close: (sz.monthly_returns(close),
                                                          pd.DataFrame(True, index=sz.monthly_returns(close).index,
                                                                       columns=syms), "point_in_time"))
    svc._base.clear()
    svc._periods.clear()
    yield svc
    svc._base.clear()
    svc._periods.clear()


def test_view_lists_rising_and_falling_stocks_with_the_checks(market):
    v = market.view("11")
    assert v["period"]["name"] == "November" and v["bench"] == "NIFTY 500"
    assert {r["side"] for r in v["rows"]} == {"bullish", "bearish"}
    assert all(r["n"] >= 6 for r in v["rows"]) and v["rows"][0]["company"].endswith("Ltd")
    assert set(v["counts"]["chance"]) >= {"bullish", "bearish", "bullish_p95", "bearish_p95"}
    assert v["test"]["universe"] == "point_in_time" and v["test"]["cost_pct"] > 0
    assert v["test"]["pooled"]["n"] >= len(v["test"]["rows"])
    assert [s["industry"] for s in v["sectors"]] == ["Alpha", "Beta"]
    assert len(v["periods"]) == 18 and "SEBI" not in v["note"]
    s = market.view("festive")
    assert s["period"]["kind"] == "season" and s["period"]["months"] == (10, 11)


def test_view_rejects_an_unknown_period(market):
    from web.api.errors import ApiException
    with pytest.raises(ApiException):
        market.view("13")


def test_seasonal_route(market):
    from fastapi.testclient import TestClient
    from web.api.main import create_app
    c = TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    r = c.get("/api/seasonal?period=11")
    assert r.status_code == 200 and r.json()["period"]["key"] == "11"
    assert c.get("/api/seasonal?period=budget").json()["period"]["months"] == [1, 2]
    assert c.get("/api/seasonal?period=13").status_code == 422 or c.get("/api/seasonal?period=13").status_code == 400
    assert c.get("/api/seasonal?period=DROP;").status_code == 422          # only a-z, 0-9, _
