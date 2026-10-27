"""Price store repairs: missing NSE sessions, NSE fills in our price units, like-for-like gap checks,
corporate-action notices around the ex-date, and the daily scan keeping refresh_store's info."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from scanner import corporate, daily, nse, store
from scanner.nse import DayFile
from scanner.providers import empty_frame
from scanner.settings import IST


def nse_world(monkeypatch, tmp_path, days: dict, holidays=()):
    """Fake NSE archive. days: date -> {symbol: (open, close, prev_close)} (raw prices)."""
    def fetch_day(d, use_cache=True):
        if d in days:
            rows = days[d]
            o = [v[0] for v in rows.values()]
            c = [v[1] for v in rows.values()]
            st = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99,
                               "close": c, "volume": 1e5, "prev_close": [v[2] for v in rows.values()],
                               "deliv_pct": 40.0}, index=pd.Index(list(rows), name="symbol"))
            return DayFile(d, "ok", st, None)
        return DayFile(d, "holiday" if d in holidays else "missing")
    monkeypatch.setattr(nse, "NSE_DIR", tmp_path)
    monkeypatch.setattr(nse, "fetch_day", fetch_day)
    monkeypatch.setattr(nse, "fetch_days", lambda ds, workers=4: {d: fetch_day(d) for d in ds})
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)


def notices(monkeypatch, by_day: dict):
    """Fake notice files. by_day: date -> {(symbol, ex-date iso): [purposes]}."""
    monkeypatch.setattr(corporate, "_notice_index", lambda d: by_day.get(d, {}))


def ours(closes: dict, dates, units: float = 1.0) -> dict:
    """Store-like frames from raw closes (NaN = no price), in `units` x NSE's raw prices."""
    c = pd.DataFrame(closes, index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates], name="date"),
                     dtype=float) * units
    return {"open": c.copy(), "high": c * 1.01, "low": c * 0.99, "close": c.copy(),
            "volume": c * 0 + 1e5, "deliv_pct": c * np.nan}


# ------------------------------------------------------------------ 1. missing sessions
JAN = [date(2024, 1, d) for d in (17, 18, 19, 20, 23)]       # 20 Jan 2024: Saturday special session
IFCI = {JAN[0]: (30.9, 31.0, 30.8), JAN[1]: (31.0, 31.45, 31.0), JAN[2]: (31.75, 32.10, 31.45),
        JAN[3]: (32.30, 38.50, 32.10), JAN[4]: (41.40, 40.00, 38.50)}


def ifci_world(monkeypatch, tmp_path):
    nse_world(monkeypatch, tmp_path, {d: {"X": v} for d, v in IFCI.items()},
              holidays={date(2024, 1, 22)})
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])


def test_gap_across_a_missing_session_is_not_a_data_correction(monkeypatch, tmp_path):
    # Yahoo lacks the Saturday session; IFCI rose 20% on it. Comparing our Fri -> Tue move with NSE's
    # Sat -> Tue move used to "correct" the whole earlier history by x1.199.
    ifci_world(monkeypatch, tmp_path)
    days = [d for d in JAN if d != JAN[3]]
    fr = ours({"X": [IFCI[d][1] for d in days]}, days, units=0.5)     # back-adjusted for a later split
    assert store._event_factor(fr, "X", pd.Timestamp(JAN[4]), nse.fetch_day(JAN[4]), []) is None


def test_repair_adds_the_missing_session_in_our_units(monkeypatch, tmp_path):
    ifci_world(monkeypatch, tmp_path)
    days = [d for d in JAN if d != JAN[3]]
    fr = ours({"X": [IFCI[d][1] for d in days]}, days, units=0.5)
    before = fr["close"]["X"].copy()
    holidays: set[str] = set()
    rep = store._repair_history(fr, ["X"], log=lambda *_: None, holidays=holidays)
    assert rep["sessions_added"] == ["2024-01-20"] and rep["adjusted"] == []
    assert fr["close"].at[pd.Timestamp(JAN[3]), "X"] == pytest.approx(38.50 * 0.5)
    assert fr["volume"].at[pd.Timestamp(JAN[3]), "X"] == pytest.approx(1e5 / 0.5)
    assert fr["close"]["X"].reindex(before.index).tolist() == pytest.approx(before.tolist())   # history untouched
    assert {"2024-01-21", "2024-01-22"} <= holidays       # Sunday and the holiday: not asked again


def test_unknown_previous_day_allows_only_a_listed_action(monkeypatch, tmp_path):
    ifci_world(monkeypatch, tmp_path)
    monkeypatch.setattr(nse, "fetch_day", lambda d, use_cache=True: DayFile(d, "error"))
    days = [d for d in JAN if d != JAN[3]]
    fr = ours({"X": [IFCI[d][1] for d in days]}, days, units=0.5)
    fl = DayFile(JAN[4], "ok", pd.DataFrame({"open": [41.4], "close": [40.0], "prev_close": [38.5]},
                                            index=pd.Index(["X"], name="symbol")))
    assert store._event_factor(fr, "X", pd.Timestamp(JAN[4]), fl, []) is None
    # A listed 1:1 bonus is still applied (best effort with NSE's previous close).
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: ["BONUS 1:1"])
    raw = ours({"X": [31.0, 31.45, 32.10, 16.05]}, days)          # raw data, halved on the ex-date
    fl = DayFile(JAN[4], "ok", pd.DataFrame({"open": [16.0], "close": [16.05], "prev_close": [32.10]},
                                            index=pd.Index(["X"], name="symbol")))
    adj = store._event_factor(raw, "X", pd.Timestamp(JAN[4]), fl, [])
    assert adj["factor"] == pytest.approx(0.5) and adj["reason"] == "BONUS 1:1"


def test_gap_across_a_symbol_change_keeps_nse_base_price(monkeypatch, tmp_path):
    # OLD's last trade 100; NEW lists two days later with NSE's base price 50 (2 NEW for 1 OLD).
    d0, d1, d2 = date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 6)
    nse_world(monkeypatch, tmp_path, {d1: {"OLD": (99, 100, 98)}, d2: {"NEW": (50, 51, 50)}})
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: "OLD" if d < d2 else s)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])
    fr = ours({"NEW": [98, 100, np.nan, 51]}, [d0, d1, date(2025, 3, 5), d2])
    adj = store._event_factor(fr, "NEW", pd.Timestamp(d2), nse.fetch_day(d2), [])
    assert adj["factor"] == pytest.approx(0.5)


def test_genuine_move_across_a_trading_gap_is_kept(monkeypatch, tmp_path):
    # FORCEMOT Oct 2023 -> Feb 2024: no EQ trades for 3 months, NSE's previous close (4424.80) is from
    # another series; both our data and NSE went 3352.35 -> 4422.65. Not a corporate action.
    d0, d1 = date(2023, 10, 25), date(2024, 2, 14)
    nse_world(monkeypatch, tmp_path, {d0: {"X": (3500, 3352.35, 3528.75)}, d1: {"X": (4424.8, 4422.65, 4424.80)}})
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])
    dates = [date(2023, 10, 23), d0] + [d0 + timedelta(days=i) for i in (6, 30, 60)] + [d1]
    fr = ours({"X": [3528.75, 3352.35, np.nan, np.nan, np.nan, 4422.65]}, dates)
    assert store._event_factor(fr, "X", pd.Timestamp(d1), nse.fetch_day(d1), []) is None


@pytest.mark.parametrize("units, expected", [(1.0, 10.0), (10.0, None)])
def test_consolidation_while_not_trading_uses_nse_base_price(monkeypatch, tmp_path, units, expected):
    # CCAVENUE Oct 2026: last trade 13.83, a week later NSE's previous close is 138.30 (10:1
    # consolidation, no notice) and it opens near it. Raw data -> x10; already adjusted -> nothing.
    d0, d1 = date(2026, 10, 12), date(2026, 10, 19)
    nse_world(monkeypatch, tmp_path, {d0: {"X": (14, 13.83, 14.1)}, d1: {"X": (135.65, 130.05, 138.30)}})
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])
    fr = ours({"X": [14.1, 13.83, np.nan, 130.05 / units]}, [date(2026, 10, 9), d0, date(2026, 10, 16), d1],
              units=units)
    adj = store._event_factor(fr, "X", pd.Timestamp(d1), nse.fetch_day(d1), [])
    assert (adj["factor"] if adj else None) == (pytest.approx(expected) if expected else None)


def test_placeholder_base_price_after_long_suspension_is_not_an_adjustment(monkeypatch, tmp_path):
    # BCG Jul 2025: last trade Rs 10.25 in Dec 2024, NSE base Rs 2.00, opened at Rs 21.80: a real re-pricing.
    d0, d1 = date(2024, 12, 30), date(2025, 7, 14)
    nse_world(monkeypatch, tmp_path, {d0: {"X": (10.5, 10.25, 10.6)}, d1: {"X": (21.80, 20.71, 2.00)}})
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])
    fr = ours({"X": [10.6, 10.25, 20.71]}, [date(2024, 12, 27), d0, d1])
    assert store._event_factor(fr, "X", pd.Timestamp(d1), nse.fetch_day(d1), []) is None


def test_empty_dates_are_dropped(monkeypatch, tmp_path):
    days = [date(2026, 1, 14), date(2026, 1, 15), date(2026, 1, 16)]   # 15 Jan 2026: NSE holiday
    nse_world(monkeypatch, tmp_path, {days[0]: {"X": (10, 10, 10)}, days[2]: {"X": (10, 10, 10)}},
              holidays={days[1]})
    fr = ours({"X": [10, np.nan, 10]}, days)
    holidays: set[str] = set()
    rep = store._repair_history(fr, ["X"], log=lambda *_: None, holidays=holidays)
    assert rep["empty_rows"] == 1 and pd.Timestamp(days[1]) not in fr["close"].index
    assert "2026-01-15" in holidays and rep["sessions_added"] == []


# ------------------------------------------------------------------ 2. NSE fills in our units
def test_stale_day_refilled_in_our_units_without_fake_corrections(monkeypatch, tmp_path):
    # 18 Mar 2025: Yahoo repeated the previous close with zero volume for ~470 stocks. The removed bars
    # used to be refilled with NSE's raw prices, and stocks whose later bonus made raw/adjusted >= 1.2
    # got a "data correction" that left their history in the wrong units (CONCOR x1.25, KVB x1.2).
    days = [date(2025, 3, d) for d in (13, 17, 18, 19)]
    raw = {"CONCOR": [640.25, 643.55, 663.05, 684.20], "KVB": [186.71, 197.52, 199.55, 201.14],
           "OK": [100.0, 101.0, 102.0, 103.0]}
    units = {"CONCOR": 0.8, "KVB": 1 / 1.2, "OK": 1.0}               # Yahoo: adjusted for later bonuses
    world = {d: {s: (raw[s][i] * 0.995, raw[s][i], raw[s][i - 1] if i else raw[s][i]) for s in raw}
             for i, d in enumerate(days)}
    nse_world(monkeypatch, tmp_path, world)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])
    fr = ours({s: np.array(v) * units[s] for s, v in raw.items()}, days)
    ts = pd.Timestamp(days[2])
    stale = ["CONCOR", "KVB"]
    for f in ("open", "high", "low", "close"):
        fr[f].loc[ts, stale] = fr["close"].loc[pd.Timestamp(days[1]), stale]   # copy of the day before
    fr["volume"].loc[ts, stale] = 0
    rep = store._repair_history(fr, list(raw), log=lambda *_: None, holidays=None)
    assert rep["flat_bars"] == 2 and rep["filled_prices"] == 2 and rep["adjusted"] == []
    for s in raw:
        assert fr["close"][s].tolist() == pytest.approx([v * units[s] for v in raw[s]])


def test_fill_stops_at_a_possible_ex_date(monkeypatch, tmp_path):
    days = [date(2025, 6, d) for d in (2, 3, 4, 5)]
    world = {days[0]: {"X": (100, 100, 100)}, days[1]: {"X": (100, 102, 100)},
             days[2]: {"X": (55, 52, 102)},            # opened 46% lower: a split/bonus ex-date?
             days[3]: {"X": (52, 53, 52)}}
    nse_world(monkeypatch, tmp_path, world)
    fr = ours({"X": [50, np.nan, np.nan, 26.5]}, days)  # ours: adjusted x0.5 for that action
    n_days, n_prices = store._fill_from_nse(fr, ["X"])
    assert (n_days, n_prices) == (1, 1)
    assert fr["close"]["X"].iloc[1] == pytest.approx(51) and np.isnan(fr["close"]["X"].iloc[2])


def test_incomplete_full_file_completed_from_old_bhavcopy(monkeypatch, tmp_path):
    # NSE's sec_bhavdata_full for 7 Mar 2022 lacks ~280 stocks (JSWENERGY, TRIDENT ...); the cm file has them.
    import io
    import zipfile
    full = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
            "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
            "RELIANCE, EQ, 07-Mar-2022, 2325.55, 2278.7, 2290, 2250, 2240, 2239.55, 2260, 100, 1, 1, 50, 50.0\n")
    cm = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
          "RELIANCE,EQ,2278.7,2290,2250,2239.55,2240,2325.55,100,1,07-MAR-2022,1,X,\n"
          "JSWENERGY,EQ,318.05,320,310,312.7,312,329.05,1000,1,07-MAR-2022,1,Y,\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm07MAR2022bhav.csv", cm)
    monkeypatch.setattr(nse, "NSE_DIR", tmp_path)
    monkeypatch.setattr(nse, "MIN_STOCK_ROWS", 1)
    monkeypatch.setattr(nse, "_get", lambda url: (200, full) if "sec_bhavdata_full" in url else (404, ""))
    monkeypatch.setattr(nse, "_get_bytes", lambda url: (200, buf.getvalue()))
    fl = nse.fetch_day(date(2022, 3, 7), use_cache=False)
    assert fl.status == "ok" and sorted(fl.stocks.index) == ["JSWENERGY", "RELIANCE"]
    assert fl.stocks.loc["RELIANCE", "deliv_pct"] == 50.0 and fl.stocks.loc["JSWENERGY", "close"] == 312.7


# ------------------------------------------------------------------ 3. notices around the ex-date
def test_notice_days_like_point_in_time_build():
    idx = pd.DatetimeIndex(pd.bdate_range("2025-06-02", periods=10), name="date")
    got = store._notice_days(idx, idx[5])
    assert got == [idx[5].date(), idx[4].date(), idx[6].date(), idx[3].date(), idx[2].date(), idx[7].date()]


def test_moved_ex_date_counts_only_on_its_new_date(monkeypatch):
    may = lambda d: date(2024, 5, d)                                   # noqa: E731
    notices(monkeypatch, {may(14): {("INOXWIND", "2024-05-17"): ["BONUS 3:1"]},
                          may(16): {("INOXWIND", "2024-05-24"): ["BONUS 3:1"]},
                          may(23): {("INOXWIND", "2024-05-24"): ["BONUS 3:1"]}})
    assert corporate.listed_on(may(17), [may(17), may(16), may(20), may(15), may(14)]) == {}
    assert corporate.listed_on(may(24), [may(24), may(23), may(27)]) == {"INOXWIND": ["BONUS 3:1"]}


def test_listed_action_found_in_the_ex_date_file_and_safe_to_repeat(monkeypatch, tmp_path):
    days = [date(2025, 6, d) for d in (11, 12, 13)]
    nse_world(monkeypatch, tmp_path, {days[1]: {"X": (990, 1000, 980)}, days[2]: {"X": (500, 505, 1000)}})
    notices(monkeypatch, {days[2]: {("X", "2025-06-13"): ["BONUS 1:1"]}})   # only in the ex-date's own file
    fr = ours({"X": [980, 1000, 505]}, days)
    found = store._check_listed_actions(fr, days[2], nse.fetch_day(days[2]))
    assert [a["factor"] for a in found] == pytest.approx([0.5]) and found[0]["reason"] == "BONUS 1:1"
    assert fr["close"]["X"].tolist() == pytest.approx([490, 500, 505])
    assert store._check_listed_actions(fr, days[2], nse.fetch_day(days[2])) == []


class FakeYahoo:
    data: dict = {}
    outage = False

    def __init__(self):
        self.errors = {}

    def history(self, symbols, starts, end, progress=None):
        return {s: self.data[s].loc[pd.Timestamp(starts[s]):pd.Timestamp(end)] if s in self.data else empty_frame()
                for s in symbols}


def refresh_env(monkeypatch, tmp_path, today: date):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(store, "ist_today", lambda: today)
    monkeypatch.setattr(store, "ist_now", lambda: datetime(today.year, today.month, today.day, 20, 0, tzinfo=IST))
    monkeypatch.setattr(store, "YahooProvider", FakeYahoo)
    monkeypatch.setattr(store.events, "trading_holidays", lambda year: set())


def yahoo_like(px: dict) -> pd.DataFrame:
    """A Yahoo download from {date: close}."""
    y = pd.DataFrame({"close": list(px.values())}, index=pd.DatetimeIndex(list(px), name="date"))
    return y.assign(open=y["close"], high=y["close"] * 1.01, low=y["close"] * 0.99, volume=1e5)


def saved_store(meta: dict, frames: dict) -> None:
    """A store saved by an earlier scan (current repair version)."""
    st = store.PanelStore()
    st.meta.update({"repair_version": store.REPAIR_VERSION, **meta})
    st.save(frames)


def _x_world(monkeypatch, tmp_path, ex: date, factor: float, by_day: dict) -> dict:
    """X trades 1000, 1001, ... on business days from 1 May to 13 Jun 2025; from `ex` on NSE's raw prices are
    x`factor` (a corporate action). Yahoo's copy ends on 11 Jun. Returns the raw prices."""
    days = list(pd.bdate_range("2025-05-01", "2025-06-13").date)
    px = {d: (1000.0 + i) * (factor if d >= ex else 1) for i, d in enumerate(days)}
    world = {d: {"X": (px[d], px[d], px[days[i - 1]] if i else px[d])} for i, d in enumerate(days)}
    nse_world(monkeypatch, tmp_path, world)
    notices(monkeypatch, by_day)
    y = pd.DataFrame({"close": [px[d] for d in days[:-2]]}, index=pd.DatetimeIndex(days[:-2], name="date"))
    FakeYahoo.data = {"X": y.assign(open=y["close"], high=y["close"] * 1.01, low=y["close"] * 0.99, volume=1e5)}
    return px


def test_refresh_applies_a_notice_listed_only_the_day_after(monkeypatch, tmp_path):
    # A demerger has no ratio the price alone could reveal: the notice decides, and NSE lists it only on 13 Jun.
    ex, after = date(2025, 6, 12), date(2025, 6, 13)
    px = _x_world(monkeypatch, tmp_path, ex, 0.7, {after: {("X", ex.isoformat()): ["DEMERGER"]}})
    log = lambda *_: None                                              # noqa: E731

    refresh_env(monkeypatch, tmp_path, ex)                            # evening of the ex-date
    fr, info = store.refresh_store(["X"], 60, log=log)
    assert fr["close"].at[pd.Timestamp(ex), "X"] == pytest.approx(px[ex]) and info["corporate_actions"] == []

    refresh_env(monkeypatch, tmp_path, after)                         # next evening: the notice appears
    fr, info = store.refresh_store(["X"], 60, log=log)
    assert [(a["date"], a["factor"]) for a in info["corporate_actions"]] == [
        (ex.isoformat(), pytest.approx(px[ex] / px[date(2025, 6, 11)], rel=1e-5))]
    c = fr["close"]["X"].dropna()
    assert (c.pct_change().dropna().abs() < 0.01).all()                # no fake 30% crash left
    assert store.PanelStore().meta["corporate_actions"][-1]["reason"] == "DEMERGER"


def test_refresh_adjusts_a_split_nse_never_listed(monkeypatch, tmp_path):
    # SHRIRAMFIN / 360ONE style: a 1:5 split without a notice on the ex-date, added from NSE's raw file. The
    # clean ratio is applied at once; the notice that turns up the next day then finds nothing left to do.
    ex, after = date(2025, 6, 12), date(2025, 6, 13)
    _x_world(monkeypatch, tmp_path, ex, 0.2, {after: {("X", ex.isoformat()): ["FV SPLT FRM RS 10 TO 2"]}})
    log = lambda *_: None                                              # noqa: E731

    refresh_env(monkeypatch, tmp_path, ex)
    fr, info = store.refresh_store(["X"], 60, log=log)
    assert [(a["date"], a["factor"]) for a in info["corporate_actions"]] == [(ex.isoformat(), 0.2)]
    assert info["corporate_actions"][0]["reason"].startswith("no NSE notice")
    assert (fr["close"]["X"].dropna().pct_change().dropna().abs() < 0.01).all()   # no fake 80% crash

    refresh_env(monkeypatch, tmp_path, after)
    fr, info = store.refresh_store(["X"], 60, log=log)
    assert info["corporate_actions"] == []                            # not applied a second time
    assert (fr["close"]["X"].dropna().pct_change().dropna().abs() < 0.01).all()


def test_scheme_notice_without_a_price_effect_is_left_alone(monkeypatch, tmp_path):
    days = [date(2025, 6, d) for d in (11, 12, 13)]
    nse_world(monkeypatch, tmp_path, {days[1]: {"UP": (99, 100, 98), "DEM": (99, 100, 98)},
                                      days[2]: {"UP": (103, 104, 100), "DEM": (70, 71, 100)}})
    notices(monkeypatch, {days[2]: {("UP", "2025-06-13"): ["SCHEME OF ARRANGEMENT"],
                                    ("DEM", "2025-06-13"): ["DEMERGER"]}})
    fr = ours({"UP": [98, 100, 104], "DEM": [98, 100, 71]}, days)
    found = store._check_listed_actions(fr, days[2], nse.fetch_day(days[2]))
    assert [(a["symbol"], a["factor"]) for a in found] == [("DEM", pytest.approx(0.7))]
    assert fr["close"]["UP"].tolist() == [98, 100, 104]               # a 3% gap up is news, not a scheme's effect


def test_old_repair_version_downloads_history_again_once(monkeypatch, tmp_path):
    days = list(pd.bdate_range("2025-05-01", "2025-06-13").date)
    world = {d: {"X": (100.0 + i, 100.0 + i, 99.0 + i if i else 100.0)} for i, d in enumerate(days)}
    nse_world(monkeypatch, tmp_path, world)
    notices(monkeypatch, {})
    good = pd.DataFrame({"close": [100.0 + i for i in range(len(days))]}, index=pd.DatetimeIndex(days, name="date"))
    good = good.assign(open=good["close"], high=good["close"] * 1.01, low=good["close"] * 0.99, volume=1e5)
    refresh_env(monkeypatch, tmp_path, days[-1])
    # A store from the old repair: history before 20 May scaled by a wrong "data correction" x1.2.
    bad = {f: good[[f]].rename(columns={f: "X"}) for f in ("open", "high", "low", "close", "volume")}
    for f in ("open", "high", "low", "close"):
        bad[f].loc[:pd.Timestamp("2025-05-19")] *= 1.2
    bad["deliv_pct"] = bad["close"] * np.nan
    st = store.PanelStore()
    st.meta.update({"repaired_v1": True, "symbols": {"X": {"full_from": "2025-04-01"}},
                    "corporate_actions": [{"symbol": "X", "date": "2025-05-20", "factor": 1.2,
                                           "reason": "data correction (matched to NSE)"}]})
    st.save(bad)
    FakeYahoo.data = {"X": good}
    fr, _ = store.refresh_store(["X"], 60, log=lambda *_: None)
    assert fr["close"]["X"].dropna().tolist() == pytest.approx(good["close"].tolist())
    meta = store.PanelStore().meta
    assert meta["repair_version"] == store.REPAIR_VERSION and meta["corporate_actions"] == []
    FakeYahoo.data = {}                                                # second run: no new download
    fr, _ = store.refresh_store(["X"], 60, log=lambda *_: None)
    assert fr["close"]["X"].dropna().tolist() == pytest.approx(good["close"].tolist())


def test_stored_prices_are_never_overwritten_with_raw_nse_ones(monkeypatch, tmp_path):
    # X's 1:1 bonus on 10 Jun is already applied to its stored history. Y is new and Yahoo's copy of it ends on
    # 5 Jun, so NSE's files from 6 Jun on are merged again: they may fill Y's gaps, but X's raw pre-bonus prices
    # must not come back (the bonus check would then halve X's older history a second time).
    days = list(pd.bdate_range("2025-05-01", "2025-06-13").date)
    ex, y_end = date(2025, 6, 10), date(2025, 6, 5)
    raw = {"X": {d: (1000.0 + i) / (2 if d >= ex else 1) for i, d in enumerate(days)},
           "Y": {d: 500.0 + i for i, d in enumerate(days)}}
    nse_world(monkeypatch, tmp_path, {d: {s: (raw[s][d], raw[s][d], raw[s][days[i - 1]] if i else raw[s][d])
                                          for s in raw} for i, d in enumerate(days)})
    notices(monkeypatch, {ex: {("X", ex.isoformat()): ["BONUS 1:1"]}})
    refresh_env(monkeypatch, tmp_path, days[-1])
    saved_store({"symbols": {"X": {"full_from": "2025-04-01"}}},
                ours({"X": [(1000.0 + i) / 2 for i in range(len(days) - 1)]}, days[:-1]))   # bonus applied
    before = store.load_store()["close"]["X"].copy()
    FakeYahoo.data = {"Y": yahoo_like({d: v for d, v in raw["Y"].items() if d <= y_end})}
    fr, info = store.refresh_store(["X", "Y"], 60, log=lambda *_: None)
    assert info["corporate_actions"] == []
    assert fr["close"]["X"].reindex(before.index).tolist() == pytest.approx(before.tolist())   # not re-adjusted
    assert fr["close"].at[pd.Timestamp(days[-1]), "X"] == pytest.approx(raw["X"][days[-1]])
    assert fr["close"]["Y"].dropna().tolist() == pytest.approx(list(raw["Y"].values()))      # gaps filled from NSE


def test_symbol_back_in_the_list_is_downloaded_again(monkeypatch, tmp_path):
    # Y left the list after 20 May and is back (a config switch, an index rebalance): the days NSE's files added
    # meanwhile covered only the list of the time, so Y is downloaded again instead of keeping a hole for good.
    days = list(pd.bdate_range("2025-05-01", "2025-06-13").date)
    px = {d: 100.0 + i for i, d in enumerate(days)}
    nse_world(monkeypatch, tmp_path, {d: {s: (px[d], px[d], px[days[i - 1]] if i else px[d]) for s in ("X", "Y")}
                                      for i, d in enumerate(days)})
    notices(monkeypatch, {})
    refresh_env(monkeypatch, tmp_path, days[-1])
    gone = date(2025, 5, 20)
    saved_store({"active": ["X"], "symbols": {s: {"full_from": "2025-04-01"} for s in ("X", "Y")}},
                ours({"X": [px[d] for d in days[:-1]], "Y": [px[d] if d <= gone else np.nan for d in days[:-1]]},
                     days[:-1]))
    FakeYahoo.data = {"Y": yahoo_like({d: px[d] for d in days[:-1]})}
    fr, _ = store.refresh_store(["X", "Y"], 60, log=lambda *_: None)
    assert fr["close"]["Y"].dropna().tolist() == pytest.approx([px[d] for d in days])
    assert store.PanelStore().meta["active"][-2:] == ["X", "Y"]


def test_day_filled_from_yahoo_is_removed_when_nse_calls_it_a_holiday(monkeypatch, tmp_path):
    days = list(pd.bdate_range("2025-05-01", "2025-06-13").date)
    hol = date(2025, 6, 11)                      # NSE was unreachable and Yahoo listed the day: it was a holiday
    px = {d: 100.0 + i for i, d in enumerate(days)}
    nse_world(monkeypatch, tmp_path, {d: {"X": (px[d], px[d], px[d])} for d in days if d != hol}, holidays={hol})
    notices(monkeypatch, {})
    refresh_env(monkeypatch, tmp_path, days[-1])
    saved_store({"symbols": {"X": {"full_from": "2025-04-01"}}, "provisional": [hol.isoformat()]},
                ours({"X": [px[d] for d in days[:-1]]}, days[:-1]))
    fr, _ = store.refresh_store(["X"], 60, log=lambda *_: None)
    assert pd.Timestamp(hol) not in fr["close"].index and pd.Timestamp(days[-1]) in fr["close"].index
    meta = store.PanelStore().meta
    assert meta["provisional"] == [] and hol.isoformat() in meta["holidays"]


class FakeFyers:
    def __init__(self, quotes: dict):
        self.quotes = quotes

    def live_rows(self, symbols):
        return {s: q for s, q in self.quotes.items() if s in symbols}


def test_live_candle_skips_untraded_quotes_and_tops_up_from_yahoo(monkeypatch, tmp_path):
    days = list(pd.bdate_range("2025-05-01", "2025-06-13").date)
    today, px = days[-1], {d: 100.0 + i for i, d in enumerate(days)}
    nse_world(monkeypatch, tmp_path, {d: {s: (px[d], px[d], px[d]) for s in "XYZ"} for d in days[:-1]})
    notices(monkeypatch, {})
    refresh_env(monkeypatch, tmp_path, today)
    monkeypatch.setattr(store, "ist_now", lambda: datetime(2025, 6, 13, 11, 0, tzinfo=IST))   # during the session
    saved_store({"symbols": {s: {"full_from": "2025-04-01"} for s in "XYZ"}},
                ours({s: [px[d] for d in days[:-1]] for s in "XYZ"}, days[:-1]))
    FakeYahoo.data = {"Z": yahoo_like(px)}                             # Z is missing from FYERS' reply
    fyers = FakeFyers({"X": (today, {"open": 0, "high": 0, "low": 0, "close": 140.0, "volume": 0}),   # no trade yet
                       "Y": (today, {"open": 141.0, "high": None, "low": 0, "close": 142.0, "volume": 5e4})})
    fr, info = store.refresh_store(list("XYZ"), 60, fyers=fyers, log=lambda *_: None)
    t = pd.Timestamp(today)
    assert np.isnan(fr["close"].at[t, "X"])                            # left on its last close
    assert (fr["open"].at[t, "Y"], fr["high"].at[t, "Y"], fr["low"].at[t, "Y"]) == (141.0, 142.0, 141.0)
    assert fr["close"].at[t, "Z"] == pytest.approx(px[today])
    assert info["live_count"] == 2 and info["live_source"].startswith("Fyers (real-time) + Yahoo for 1")


# ------------------------------------------------------------------ 4. daily scan keeps refresh info
def test_daily_result_keeps_refresh_info_when_a_strategy_has_actions(monkeypatch, frames_factory, tmp_path):
    from scanner.engine import SimResult
    n = 300
    fr = frames_factory({"A": np.linspace(100, 200, n), "B": np.linspace(100, 150, n), "NIFTY50": [1000.0] * n})
    fr["deliv_pct"] = fr["close"] * np.nan
    info = {"complete_upto": str(fr["close"].index[-1].date()), "live_day": None, "live_source": "Fyers (real-time)",
            "nse_status": "NSE official data to today", "errors": {"ZZZ": "no data"},
            "corporate_actions": [{"symbol": "A", "date": "2025-01-01", "factor": 0.5, "reason": "BONUS 1:1"}]}
    monkeypatch.setattr(daily, "get_fyers", lambda cfg: (None, "no fyers"))
    monkeypatch.setattr(daily, "get_universe", lambda name: (
        pd.DataFrame({"symbol": ["A", "B"], "company": ["A Ltd", "B Ltd"], "industry": ["X", "Y"]}), "test list"))
    monkeypatch.setattr(daily, "industry_map", lambda: {})          # no NSE download from a test
    monkeypatch.setattr(daily, "load_holdings", lambda: pd.DataFrame(
        columns=["symbol", "qty", "buy_price", "buy_date", "stop_loss_pct", "target_pct"]))
    monkeypatch.setattr(daily, "refresh_store", lambda *a, **k: (fr, dict(info)))
    monkeypatch.setattr(daily, "upcoming_results", lambda syms, day, days=14: ({"A": "2099-01-01"}, "note"))
    # no NSE downloads and no writes to the real data/results caches from a test
    monkeypatch.setattr(daily, "results_history", lambda start, end, log=print: {})
    monkeypatch.setattr(daily, "index_history", lambda days, log=print: pd.DataFrame())
    monkeypatch.setattr(daily, "TIMING_CACHE", tmp_path / "timing_cache.json")
    monkeypatch.setattr(daily, "REJECTED_CACHE", tmp_path / "rejected_cache.json")
    eq = pd.Series(np.linspace(1, 2, n), index=fr["close"].index)
    res = SimResult("momentum", eq, eq * 0 + 1, [], [], [{"action": "BUY", "symbol": "A", "reason": "top"}], 0)
    monkeypatch.setattr(daily, "simulate", lambda *a, **k: res)
    monkeypatch.setattr(daily.paper, "record_scan", lambda result: None)
    monkeypatch.setattr(daily.paper, "summaries", lambda *a, **k: {})
    saved = {}
    monkeypatch.setattr(daily, "_save", lambda result, *a, **k: saved.update(result))
    cfg = {"backtest_universe": "current", "filters": {"min_price": 0, "min_turnover_cr": 0},
           "strategies": {"momentum": {"enabled": True}, "near_high": {"enabled": False},
                          "trend_breakout": {"enabled": False}, "rsi2_pullback": {"enabled": False},
                          "low_vol": {"enabled": False}}}
    out = daily._run_daily(cfg, True, None, lambda *_: None)
    assert out["strategies"][0]["actions"][0]["results_on"] == "2099-01-01"
    assert saved["live_source"] == "Fyers (real-time)" and saved["nse_status"] == "NSE official data to today"
    assert saved["errors"] == {"ZZZ": "no data"} and saved["corporate_actions"][0]["symbol"] == "A"
