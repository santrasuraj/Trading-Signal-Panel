"""Options verdict (scanner/option_verdict.py) and big-money parsers (scanner/big_money.py)."""
import numpy as np
import pandas as pd
import pytest

from scanner import big_money as bm
from scanner import option_verdict as ov


def _close(n=900, seed=3, vol=0.02):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.Series(1000 * np.exp(np.cumsum(rng.normal(0, vol, n))), index=idx)


def _chain(spot, call_px, put_px, day="2026-11-04", days=14.0, oi=5000):
    rows = []
    for k in np.arange(spot - 50, spot + 51, 10):
        rows.append({"strike": float(k), "atm": abs(k - spot) < 5,
                     "ce": {"ltp": call_px, "bid": call_px * 0.98, "ask": call_px, "oi": oi, "iv_pct": 30.0, "delta": 0.5},
                     "pe": {"ltp": put_px, "bid": put_px * 0.98, "ask": put_px, "oi": oi, "iv_pct": 30.0, "delta": -0.5}})
    return {"symbol": "TEST", "expiry": "2026-11-18", "time": f"{day}T15:30:00+05:30", "spot": spot, "atm": spot,
            "days_to_expiry": days, "summary": {"atm_iv_pct": 30.0}, "rows": rows}


def _match(better=True):
    s = {"n": 5000, "months": 80}
    for h in (5, 10, 20):
        s[str(h)] = {"median_pct": 1.0 if better else -1.0, "excess_pct": 1.0 if better else -1.0,
                     "t": 3.0 if better else -3.0, "p25_pct": -3.0, "p75_pct": 4.0}
    return {"level": ["trend"], "stats": s, "dropped": []}


def test_no_tested_direction_is_no_trade():
    c = _close()
    v = ov.assess(_chain(float(c.iloc[-1].round(-1)), 1.0, 1.0), c, None, [], "TEST", last_day="2026-11-04")
    assert v["verdict"] == "NO_TRADE"
    assert v["direction"]["bias"] == "none"


def test_cheap_call_with_tested_direction_is_a_buy():
    c = _close()
    spot = float(c.iloc[-1].round(-1))
    v = ov.assess(_chain(spot, 0.5, 0.5), c, _match(True), [], "TEST", last_day="2026-11-04")
    assert v["direction"]["bias"] == "bullish"
    assert v["verdict"] == "BUY_CALL" and v["pick"]["side"] == "ce"
    assert v["pick"]["breakeven"] > v["pick"]["strike"]


def test_expensive_option_is_no_trade_even_with_a_direction():
    c = _close()
    spot = float(c.iloc[-1].round(-1))
    v = ov.assess(_chain(spot, spot * 0.2, spot * 0.2), c, _match(True), [], "TEST", last_day="2026-11-04")
    assert v["verdict"] == "NO_TRADE"
    assert all(not x["ok"] for x in v["calls"])


def test_old_chain_gives_no_verdict():
    c = _close()
    spot = float(c.iloc[-1].round(-1))
    v = ov.assess(_chain(spot, 0.5, 0.5, day="2026-10-30"), c, _match(True), [], "TEST", last_day="2026-11-04")
    assert v["verdict"] == "NO_DATA"


def test_working_strategy_order_counts_disagreement_cancels():
    strategies = [{"status": "working", "name": "Momentum", "actions": [{"symbol": "TEST", "action": "SELL"}]}]
    d = ov.direction(_match(True), 10, strategies, "TEST")
    assert d["bias"] == "none"                         # bullish setups vs a working strategy's sell
    d2 = ov.direction(None, 10, [{"status": "not-working", "actions": [{"symbol": "TEST", "action": "BUY"}]}], "TEST")
    assert d2["bias"] == "none"                        # a strategy that is not working never counts


def test_score_settles_at_the_expiry_close():
    idx = pd.bdate_range("2026-11-02", periods=20)
    close = pd.Series(100.0, index=idx)
    close.loc["2026-11-18":] = 110.0
    rows = [{"id": "x", "day": "2026-11-04", "symbol": "TEST", "store_symbol": "TEST", "expiry": "2026-11-18",
             "verdict": "BUY_CALL", "side": "ce", "strike": 100.0, "premium": 2.0,
             "atm_call": {"strike": 100.0, "premium": 2.0}, "atm_put": {"strike": 100.0, "premium": 2.0}}]
    out = ov.score(rows, {"TEST": close}, today=pd.Timestamp("2026-11-25").date())
    assert out[0]["settled"] and out[0]["settle_price"] == 110.0
    pay = 10 * (1 - ov.EXERCISE_STT_PCT / 100)
    cost = 2.0 * (1 + ov.COST_PCT / 100)
    assert out[0]["pick_return_pct"] == pytest.approx((pay - cost) / cost * 100, abs=0.1)
    assert out[0]["atm_put_return_pct"] == pytest.approx(-100.0)
    t = ov.track(out)
    assert t["buys"] == 1 and t["buy_wins"] == 1 and t["settled"] == 1


def test_parse_pledge_reads_the_promoter_columns():
    rec = bm.parse_pledge({"data": [{"shp": "30-Sep-2026", "broadcastDt": "04-Nov-2026 16:30:39", "comName": "JP",
                                     "percPromoterHolding": "  24.00", "totPromoterShares": "1200509465",
                                     "percPromoterShares": "  72.99", "percTotShares": " 17.52",
                                     "numSharesPledged": "2093549773", "percSharesPledged": "30.55",
                                     "totPromoterHolding": "1644700000"}]})
    assert rec["promoter_pct"] == 24.0 and rec["promoter_pledged_pct"] == 72.99
    assert rec["promoter_pledged_total_pct"] == 17.52 and rec["depository_pledged_pct"] == 30.55
    assert rec["quarter"] == "2026-09-30"
    assert bm.parse_pledge({"data": []}) is None


def test_parse_sast_sides_and_ban_list():
    df = bm.parse_sast({"data": [
        {"symbol": "ABC", "acqSaleType": "Acquisition", "noOfShareAcq": "500", "totAcqShare": "1.5", "totAftShare": "6.2",
         "promoterType": "Y", "acquirerName": "X", "timestamp": "29-Oct-2026 12:36", "attachement": "https://nse/x.zip"},
        {"symbol": "ABC", "acqSaleType": "Sale", "noOfShareSale": "300", "totSaleShare": "2.0", "totAftShare": "3.0",
         "promoterType": "N", "acquirerName": "Y", "timestamp": "30-Oct-2026 10:00"}]})
    assert list(df["side"]) == ["BUY", "SELL"] and list(df["pct"]) == [1.5, 2.0]
    assert bool(df["promoter"].iloc[0]) and df["link"].iloc[0] == "https://nse/x.zip"
    ban = bm.parse_ban("Securities in Ban For Trade Date 05-NOV-2026:\n1,KAYNES\n2,SAIL\n")
    assert ban == {"trade_date": "2026-11-05", "symbols": ["KAYNES", "SAIL"], "source": bm.BAN_URL}


def test_delivery_spike_uses_only_past_days():
    idx = pd.bdate_range("2026-01-01", periods=40)
    close = pd.DataFrame({"x": np.linspace(100, 120, 40)}, index=idx)
    vol = pd.DataFrame({"x": 1000.0}, index=idx)
    dp = pd.DataFrame({"x": 30.0}, index=idx)
    vol.iloc[-1, 0], dp.iloc[-1, 0] = 3000.0, 60.0            # today: 6x the usual delivery, 60% delivered
    fr = bm.delivery_frames(close, vol, dp)
    assert bool(fr["accumulation"].iloc[-1, 0]) and not fr["accumulation"].iloc[:-1, 0].any()
    assert fr["avg"].iloc[-1, 0] == pytest.approx(300.0)      # the average excludes today itself
