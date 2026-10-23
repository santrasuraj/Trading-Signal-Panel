"""Tests for the point-in-time (survivorship-free) universe: membership without look-ahead, rename
stitching, corporate-action adjustment of raw NSE prices, and delisted stocks in the engine."""
import io
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scanner import corporate, nse, pit, store
from scanner.costs import CostModel
from scanner.engine import RankStrategy, simulate
from scanner.panel import Factors, panel_from_wide
from scanner.strategies import tradable_mask


# ------------------------------------------------------------------ membership
def _turnover_panel(values: dict[str, list[float]]):
    """close = 1, volume = traded value, so traded value is exactly the given numbers (NaN = no trade)."""
    v = pd.DataFrame(values, dtype=float)
    close = np.where(v.isna(), np.nan, 1.0)
    return close, v.to_numpy(), np.ones(v.shape, dtype=bool)


def test_membership_picks_top_n_by_trailing_average_traded_value():
    n = 60
    close, vol, eq = _turnover_panel({"BIG": [100.0] * n, "MID": [50.0] * n, "SMALL": [10.0] * n})
    member, avg = pit.membership(close, vol, eq, size=2, window=20, min_days=5)
    assert member[-1].tolist() == [True, True, False]
    assert avg[-1, 0] == pytest.approx(100.0)
    # SMALL's turnover jumps: the 20-day average needs time to catch up - it enters only once it has.
    close, vol, eq = _turnover_panel({"BIG": [100.0] * n, "MID": [50.0] * n,
                                      "SMALL": [10.0] * 30 + [200.0] * 30})
    member, _ = pit.membership(close, vol, eq, size=2, window=20, min_days=5)
    assert not member[30, 2]                     # first big day: average still (19*10+200)/20 = 19.5
    assert member[36, 2] and not member[36, 1]   # (13*10+7*200)/20 = 76.5 > 50: SMALL replaces MID


def test_membership_has_no_lookahead():
    """The universe on day t must be the same whether or not we know anything after day t."""
    rng = np.random.default_rng(3)
    T, S = 300, 40
    vol = rng.lognormal(10, 1, (T, S))
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, S)), axis=0))
    close[rng.random((T, S)) < 0.05] = np.nan            # random missing days
    eq = np.ones((T, S), dtype=bool)
    full, _ = pit.membership(close, vol, eq, size=10, window=63, min_days=10)
    future = close.copy()
    future[200:] *= rng.lognormal(0, 2, (T - 200, S))      # a completely different future
    future[250:, :5] = np.nan                              # some stocks vanish later
    alt, _ = pit.membership(future, vol * rng.lognormal(0, 1, (T, S)) ** (np.arange(T) >= 200)[:, None], eq,
                            size=10, window=63, min_days=10)
    assert (full[:200] == alt[:200]).all()
    for t in (80, 150, 199):                                # and the same as building on data up to t only
        cut, _ = pit.membership(close[:t + 1], vol[:t + 1], eq[:t + 1], size=10, window=63, min_days=10)
        assert (cut[t] == full[t]).all()
    assert full.sum(axis=1)[100:].min() == 10


def test_membership_rules_history_stale_and_units():
    n = 80
    vals = {"OLD": [100.0] * n,
            "IPO": [np.nan] * 70 + [1000.0] * 10,            # only 10 days of history
            "DEAD": [500.0] * 50 + [np.nan] * 30,            # stopped trading on day 50
            "REIT": [900.0] * n}
    close, vol, eq = _turnover_panel(vals)
    eq[:, 3] = False                                         # REIT/InvIT units are not shares
    member, _ = pit.membership(close, vol, eq, size=3, window=40, min_days=21, stale_days=5)
    cols = list(vals)
    m = pd.DataFrame(member, columns=cols)
    assert not m["IPO"].any() and not m["REIT"].any()
    assert m["DEAD"].iloc[49] and m["DEAD"].iloc[53] and not m["DEAD"].iloc[54]   # out after 5 days without a trade
    assert m["OLD"].iloc[30:].all()


# ------------------------------------------------------------------ renames
def test_stitch_moves_old_symbol_history_and_keeps_reused_symbol():
    days = pd.to_datetime(["2020-01-01", "2020-06-01", "2021-01-01", "2022-01-01"]).to_numpy()
    sym = np.array(["A", "A", "B", "A"], dtype=object)       # A renamed to B on 2020-12-01; a new A later
    canon, moved = pit.stitch(sym, days, [("A", "B", date(2020, 12, 1))])
    assert canon.tolist() == ["B", "B", "B", "A"] and moved.tolist() == [True, True, False, False]
    # chains: X -> Y (2020-03-01) -> Z (2021-06-01)
    sym = np.array(["X", "Y", "Y", "Z"], dtype=object)
    canon, _ = pit.stitch(sym, days, [("X", "Y", date(2020, 3, 1)), ("Y", "Z", date(2021, 6, 1))])
    assert canon.tolist() == ["Z", "Z", "Z", "Z"]


def test_canonical_prefers_rows_already_under_the_new_symbol(monkeypatch):
    monkeypatch.setattr(pit, "rename_list", lambda: [("OLD", "NEW", date(2020, 1, 3))])
    raw = pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-02", "2020-01-03"]),
                        "symbol": ["OLD", "OLD", "NEW", "NEW"], "close": [10.0, 11.0, 99.0, 12.0]})
    out = pit._canonical(raw)
    assert out["symbol"].tolist() == ["NEW", "NEW", "NEW"]
    assert out["close"].tolist() == [10.0, 99.0, 12.0]


# ------------------------------------------------------------------ corporate actions on raw prices
def _raw_frames(closes: dict[str, list[float]], opens: dict[str, list[float]] | None = None):
    idx = pd.bdate_range("2025-01-01", periods=len(next(iter(closes.values()))), name="date")
    c = pd.DataFrame(closes, index=idx, dtype=float)
    o = pd.DataFrame(opens, index=idx, dtype=float) if opens else c.copy()
    fr = {"open": o, "close": c, "high": np.maximum(o, c), "low": np.minimum(o, c),
          "volume": c * 0 + 1e6, "deliv_pct": c * np.nan}
    return fr, c.ffill().shift(1)                  # prev_close: NSE's file states the raw previous close


def test_adjust_raw_nse_prices_bonus_demerger_and_crash(monkeypatch, tmp_path):
    fr, prev = _raw_frames(
        {"BON": [980, 985, 990, 1000, 505, 510], "DEM": [735, 738, 740, 773.6, 271.55, 275],
         "CRASH": [1890, 1895, 1900, 1886, 1207, 1210], "FLAT": [98, 99, 100, 101, 102, 103]},
        opens={"BON": [980, 985, 990, 1000, 500, 505], "DEM": [735, 738, 740, 773.6, 289.5, 271.55],
               "CRASH": [1890, 1895, 1900, 1886, 1697, 1207], "FLAT": [98, 99, 100, 101, 102, 103]})
    notices = {("BON", "2025-01-07"): ["BONUS 1:1"], ("DEM", "2025-01-07"): ["DEMERGER"]}
    looked_up = []

    def actions_on(sym, ex_day, prior):
        looked_up.append((sym, len(prior)))
        return notices.get((sym, ex_day.isoformat()), [])

    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "actions_on", actions_on)
    monkeypatch.setattr(corporate, "fetch_bc", lambda d: None)
    monkeypatch.setattr(pit, "NOTICES_FILE", tmp_path / "notices.parquet")
    done = pit._adjust(fr, prev, set(), log=lambda *_: None)
    by = {a["symbol"]: a for a in done}
    assert set(by) == {"BON", "DEM"}                               # the genuine crash is left alone
    assert fr["close"]["BON"].tolist() == pytest.approx([490, 492.5, 495, 500, 505, 510])
    assert fr["volume"]["BON"].iloc[0] == pytest.approx(2e6)       # twice the shares before the bonus
    assert by["DEM"]["factor"] == pytest.approx(289.5 / 773.6, rel=1e-4)
    assert fr["close"]["CRASH"].tolist() == [1890, 1895, 1900, 1886, 1207, 1210]
    assert fr["close"]["FLAT"].tolist() == [98, 99, 100, 101, 102, 103]
    assert ("CRASH", 5) in looked_up              # >20% moves: the ex-date, 3 days before and 1 after


def test_fallback_for_jumps_without_a_notice():
    d, prev_day = pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-09")
    ref = pd.DataFrame({"SPLIT": [580.0, 562.0], "CRASH": [100.0, 55.0]}, index=[prev_day, d])
    # 1. the store's Yahoo-adjusted history moved normally on that day: the gap is a split
    a = pit._fallback("SPLIT", d, 582.0, 532.0, 2809.85, prev_day, ref)
    assert a["factor"] == pytest.approx(532.0 / 2809.85 / (562.0 / 580.0), rel=1e-6)
    # ...but a crash the store also shows is real
    assert pit._fallback("CRASH", d, 60.0, 55.0, 100.0, prev_day, ref) is None
    # 2. no reference: a clean ratio (1:1 bonus) is recognised, a crash of a similar size is not
    assert pit._fallback("X", d, 251.0, 255.0, 500.0, prev_day, None)["factor"] == 0.5
    assert pit._fallback("X", d, 300.0, 255.0, 500.0, prev_day, None) is None
    assert pit._fallback("X", d, 400.0, 300.0, 500.0, prev_day, None) is None   # -20% circuit: real
    # 3. opening 60%+ lower with no notice: a special dividend (Majesco 2020: x0.012)
    assert pit._fallback("X", d, 12.0, 12.1, 1000.0, prev_day, None)["factor"] == pytest.approx(0.012)


def test_notice_table_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(pit, "NOTICES_FILE", tmp_path / "notices.parquet")
    monkeypatch.setattr(pit, "PIT_DIR", tmp_path)
    memo = {date(2025, 6, 13): pd.DataFrame({"series": ["EQ"], "symbol": ["BAJFINANCE"], "ex_date": ["2025-06-16"],
                                             "purpose": ["BONUS 4:1"]}),
            date(2025, 6, 14): None}                                   # a day with no notice file
    monkeypatch.setattr(corporate, "_bc_memo", dict(memo))
    monkeypatch.setattr(corporate, "_bc_index", {})
    monkeypatch.setattr(corporate, "fetch_bc", lambda d: corporate._bc_memo.get(d))
    pit.save_notices([date(2025, 6, 13), date(2025, 6, 14), date(2025, 6, 15)])   # the 15th: not definite
    corporate._bc_memo.clear()
    assert pit.load_notices() == {date(2025, 6, 13), date(2025, 6, 14)}
    assert corporate._bc_memo[date(2025, 6, 14)] is None
    assert corporate.actions_on("BAJFINANCE", date(2025, 6, 16), [date(2025, 6, 16), date(2025, 6, 13)]) == ["BONUS 4:1"]


def test_events_flag_small_bonus_gaps_but_not_normal_days():
    fr, prev = _raw_frames({"S": [100, 100, 90.5, 91, 92]}, opens={"S": [100, 100, 90.9, 91, 91.5]})
    ev = pit._events(fr, prev, set())
    assert [(d.date().isoformat(), s, big) for d, s, big in ev] == [("2025-01-03", "S", False)]   # 1:10 bonus gap


# ------------------------------------------------------------------ build / cache round trip
def test_build_end_to_end_without_lookahead(tmp_path, monkeypatch):
    rng = np.random.default_rng(7)
    days = list(pd.bdate_range("2023-01-02", periods=160).date)
    rows = []
    for k in range(12):
        price = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
        for i, d in enumerate(days):
            if k == 0 and i >= 120:
                break                                              # S00 is delisted on day 120
            rows.append({"date": pd.Timestamp(d), "symbol": f"S{k:02d}", "open": price[i], "high": price[i],
                         "low": price[i], "close": price[i], "volume": 1e5 * (12 - k), "prev_close": np.nan,
                         "deliv_pct": np.nan, "equity": True})
    raw = pd.DataFrame(rows)
    raw["prev_close"] = raw.groupby("symbol")["close"].shift(1)
    monkeypatch.setattr(pit, "PIT_DIR", tmp_path)
    monkeypatch.setattr(pit, "update_raw", lambda d, download=True, log=print: raw[raw["date"].isin(pd.to_datetime(d))])
    monkeypatch.setattr(pit, "rename_list", lambda: [])
    monkeypatch.setattr(pit, "_adjust", lambda *a, **k: [])
    monkeypatch.setattr(pit, "etf_symbols", lambda dates, log=print: {"S01", "NOTTRADED"})   # S01: a busy ETF
    data = pit.build(days, keep_symbols=["S11"], log=lambda *_: None, size=5)
    assert "S01" not in data.universe.columns and data.info["etfs_excluded"] == 1
    assert data.universe.sum(axis=1).iloc[30:].eq(5).all()
    assert data.universe["S00"].iloc[30:120].all() and not data.universe["S00"].iloc[125:].any()
    assert "S11" in data.universe.columns and not data.universe["S11"].any()   # kept, never a member
    assert data.info["members_no_longer_trading"] == 1
    loaded = pit.load()
    pd.testing.assert_frame_equal(loaded.universe, data.universe)
    pd.testing.assert_frame_equal(loaded.frames["close"], data.frames["close"])
    # Building with only the first 100 days gives the same universe for those days.
    early = pit.build(days[:100], log=lambda *_: None, size=5)
    shared = early.universe.columns
    pd.testing.assert_frame_equal(early.universe, data.universe.iloc[:100][shared])


# ------------------------------------------------------------------ factors and engine
def test_cross_sectional_factors_only_compare_members(frames_factory):
    n = 300
    paths = {"A": np.linspace(100, 200, n), "B": np.linspace(100, 150, n), "C": np.linspace(100, 400, n)}
    fr = frames_factory(paths)
    uni = pd.DataFrame(True, index=fr["close"].index, columns=list(paths))
    uni["C"] = False                                                 # the best stock is not a member
    f = Factors(panel_from_wide(fr, universe=uni))
    last = f.rs_rating.iloc[-1]
    assert np.isnan(last["C"]) and last["A"] > last["B"]
    assert last["A"] == 99                                           # top among members, C ignored
    assert np.isnan(f.momentum.iloc[-1]["C"])
    trad = tradable_mask(f, 0, 0)
    assert not trad["C"].any() and trad["A"].iloc[-1]
    f_all = Factors(panel_from_wide(fr))                             # no universe: everyone compared
    assert f_all.rs_rating.iloc[-1]["C"] == 99


def test_engine_sells_a_holding_that_stops_trading(frames_factory):
    n = 360
    closes = {"A": [100.0] * n, "B": [100.0] * n}
    closes["A"][290:] = [np.nan] * (n - 290)                         # A delisted after day 289
    fr = frames_factory(closes)
    fr["open"]["A"] = fr["close"]["A"]
    p = panel_from_wide(fr)
    p.index_close = pd.Series(1000.0, index=p.dates)
    f = Factors(p)
    score = pd.DataFrame({"A": 2.0, "B": 1.0}, index=p.dates)
    strat = RankStrategy("r", "r", "", score=lambda _: score, top_n=1, keep_rank=1, use_regime=False)
    res = simulate(strat, f, CostModel(), tradable=tradable_mask(f, 0, 0))
    gone = [t for t in res.trades if t.reason == "stopped trading"]
    assert len(gone) == 1 and gone[0].symbol == "A"
    assert gone[0].exit_date == p.dates[289 + 20] and gone[0].exit_price == pytest.approx(100 * (1 - 0.0025))
    assert [o["symbol"] for o in res.open_positions] == ["B"]        # money moved on at the next rebalance


# ------------------------------------------------------------------ NSE old-format bhavcopy
def test_parse_old_cm_bhavcopy():
    csv = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
           "RELIANCE,EQ,1180,1190,1170,1185.5,1185,1178.2,1000,1185500,06-AUG-2018,50,INE002A01018,\n"
           "SOMEREIT,RR,300,301,299,300,300,300,10,3000,06-AUG-2018,2,INE0000000,\n"
           "BONDX,GB,100,100,100,100,100,100,1,100,06-AUG-2018,1,IN0000,\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm06AUG2018bhav.csv", csv)
    df = nse._parse_cm(buf.getvalue(), date(2018, 8, 6))
    assert df.loc["RELIANCE", "close"] == 1185.5 and df.loc["RELIANCE", "prev_close"] == 1178.2
    assert df.loc["RELIANCE", "volume"] == 1000 and np.isnan(df.loc["RELIANCE", "deliv_pct"])
    assert df.loc["SOMEREIT", "series"] == "RR" and "BONDX" not in df.index
    with pytest.raises(nse._OtherDay):
        nse._parse_cm(buf.getvalue(), date(2018, 8, 7))


# ------------------------------------------------------------------ daily scan / paper journal wiring
def test_daily_backtest_falls_back_to_current_list_when_not_built(monkeypatch):
    from scanner import daily
    monkeypatch.setattr(pit, "update", lambda days, keep, **k: None)
    fr = {"close": pd.DataFrame({"A": [1.0]}, index=pd.DatetimeIndex(["2026-01-01"], name="date"))}
    out = daily._backtest_setup({"backtest_universe": "point_in_time"}, fr, {}, ["A"], {}, log=lambda *_: None)
    assert out["universe"] == "current" and out["f"] is None and "not available" in out["note"]
    out = daily._backtest_setup({"backtest_universe": "current"}, fr, {}, ["A"], {}, log=lambda *_: None)
    assert out["universe"] == "current" and out["f"] is None


def test_daily_backtest_uses_point_in_time_universe(monkeypatch, frames_factory):
    from scanner import daily
    n = 300
    fr = frames_factory({"A": np.linspace(100, 200, n), "B": np.linspace(100, 150, n), "GONE": [100.0] * n})
    uni = pd.DataFrame(True, index=fr["close"].index, columns=["A", "B", "GONE"])
    uni.iloc[200:, 2] = False                                   # GONE left the universe on day 200
    fr["deliv_pct"] = fr["close"] * np.nan
    data = pit.PitData(fr, uni, {"rule": {"size": 2}, "members_no_longer_trading": 1, "last_day": "2025-02-24"})
    monkeypatch.setattr(pit, "update", lambda days, keep, **k: data)
    store_fr = {f: pd.DataFrame({"NIFTY50": 1000.0, "NIFTY500": 100.0}, index=fr["close"].index)
                for f in ("open", "high", "low", "close", "volume", "deliv_pct")}
    out = daily._backtest_setup({"backtest_universe": "point_in_time"}, store_fr, {}, ["A"], {"min_price": 0,
                                "min_turnover_cr": 0}, log=lambda *_: None)
    assert out["universe"] == "point_in_time" and out["members"] == 3 and out["gone"] == 1
    assert out["trad"]["GONE"].iloc[150] and not out["trad"]["GONE"].iloc[250]
    assert out["n500"].iloc[-1] == 100.0 and out["f"].p.index_close.iloc[-1] == 1000.0


def test_paper_skips_survivorship_haircut_for_point_in_time_backtests(tmp_path):
    from scanner import paper
    from scanner.costs import CostModel
    idx = pd.bdate_range("2026-01-01", periods=30, name="date")
    close = pd.DataFrame({"A": 100.0, "NIFTY50": 1000.0, "NIFTY500": 100.0}, index=idx)
    fr = {"open": close, "high": close, "low": close, "close": close,
          "volume": pd.DataFrame(1e6, index=idx, columns=close.columns)}
    out = {}
    for universe in ("current", "point_in_time"):
        path = tmp_path / f"{universe}.sqlite"
        paper.record_scan({
            "data_date": str(idx[5].date()), "generated_at": "x", "live": False, "capital": 100_000.0,
            "strategies": [{"key": "mom", "name": "Mom", "kind": "rank", "max_positions": 2, "actions": [],
                            "positions": [], "metrics": {"full": {"cagr_pct": 20.0, "backtest_universe": universe,
                                                                  "n500_benchmark": {"cagr_pct": 12.0}}}}]}, path)
        out[universe] = paper.build_report(fr, CostModel(), path)["mom"]["summary"]
    assert out["current"]["haircut_pct"] < out["current"]["expected_pct"]
    assert out["point_in_time"]["haircut_pct"] == pytest.approx(out["point_in_time"]["expected_pct"])


def test_daily_update_reuses_checked_days(monkeypatch, tmp_path):
    """An update re-applies the previous build's verdicts and only checks new days / new stocks."""
    fr, prev = _raw_frames({"BON": [980, 985, 990, 1000, 505, 510], "NEW": [100, 100, 100, 100, 100, 60]},
                           opens={"BON": [980, 985, 990, 1000, 500, 505], "NEW": [100, 100, 100, 100, 100, 90]})
    looked_up = []
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: looked_up.append((s, d)) or [])
    monkeypatch.setattr(corporate, "fetch_bc", lambda d: None)
    monkeypatch.setattr(pit, "NOTICES_FILE", tmp_path / "notices.parquet")
    old = pit.PitData({}, pd.DataFrame(columns=["BON"]),
                      {"last_day": "2025-01-07", "adjustments": [
                          {"symbol": "BON", "date": "2025-01-07", "factor": 0.5, "reason": "BONUS 1:1"}]})
    done = pit._adjust(fr, prev, set(), log=lambda *_: None, reuse=old)
    assert [a["symbol"] for a in done] == ["BON"]                     # re-applied without a new lookup
    assert fr["close"]["BON"].tolist() == pytest.approx([490, 492.5, 495, 500, 505, 510])
    assert {s for s, _ in looked_up} == {"NEW"}                       # only the stock new to the universe


def test_listed_bonus_with_a_small_price_move_is_adjusted(monkeypatch, tmp_path):
    """Karur Vysya 2018: 1:10 bonus, but the stock rallied and opened only 4% lower."""
    fr, prev = _raw_frames({"KVB": [103.85, 103.7, 102.2, 100.1, 98.9], "ARR": [50, 50, 50, 49.0, 49]},
                           opens={"KVB": [104.95, 104.6, 102.9, 97.9, 100.0], "ARR": [50, 50, 50, 49.0, 49]})
    tab = pd.DataFrame({"series": ["EQ", "EQ"], "symbol": ["KVB", "ARR"], "ex_date": ["2025-01-06", "2025-01-06"],
                        "purpose": ["BONUS 1:10", "SCHEME OF ARRANGEMENT"], "day": pd.Timestamp("2025-01-07")})
    monkeypatch.setattr(pit, "NOTICES_FILE", tmp_path / "notices.parquet")
    tab.to_parquet(pit.NOTICES_FILE, index=False)
    monkeypatch.setattr(corporate, "_bc_memo", {})
    monkeypatch.setattr(corporate, "_bc_index", {})
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "renames", lambda: {})
    monkeypatch.setattr(corporate, "fetch_bc", lambda d: corporate._bc_memo.get(d))
    done = pit._adjust(fr, prev, set(), log=lambda *_: None)
    assert [(a["symbol"], a["date"], a["factor"]) for a in done] == [("KVB", "2025-01-06", pytest.approx(10 / 11))]
    assert fr["close"]["ARR"].tolist() == [50, 50, 50, 49.0, 49]     # a 2% move on a scheme notice: noise


def test_rescheduled_or_corrected_notices_count_once(monkeypatch, tmp_path):
    idx = pd.bdate_range("2024-05-06", "2024-05-31", name="date")
    close = pd.DataFrame({"INOX": 100.0, "HALX": 100.0}, index=idx)
    rows = [("INOX", "2024-05-17", "2024-05-09"), ("INOX", "2024-05-17", "2024-05-10"),   # first announced
            ("INOX", "2024-05-24", "2024-05-14"), ("INOX", "2024-05-24", "2024-05-23"),   # then moved
            ("HALX", "2024-05-29", "2024-05-13"), ("HALX", "2024-05-28", "2024-05-28")]   # corrected on the day
    tab = pd.DataFrame(rows, columns=["symbol", "ex_date", "day"]).assign(series="EQ", purpose="BONUS 3:1")
    tab["day"] = pd.to_datetime(tab["day"])
    monkeypatch.setattr(pit, "NOTICES_FILE", tmp_path / "notices.parquet")
    tab.to_parquet(pit.NOTICES_FILE, index=False)
    monkeypatch.setattr(corporate, "renames", lambda: {})
    listed = pit._listed_actions(close, idx)
    assert sorted((d.date().isoformat(), s) for d, s in listed) == [("2024-05-24", "INOX"), ("2024-05-28", "HALX")]
    assert listed[(pd.Timestamp("2024-05-24"), "INOX")] == [date(2024, 5, 14), date(2024, 5, 23)]
