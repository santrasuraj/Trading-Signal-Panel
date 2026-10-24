"""Static strategy metadata for the evidence card and the plain-language rules (docs/strategy_catalogue.md).

Numbers about *our* backtests never live here: they come from latest.json. This module only holds what
the published research says, what to expect, how each strategy fails, and rule wording.
"""
from __future__ import annotations

S = lambda title, url=None: {"title": title, "url": url}  # noqa: E731

CATALOG: dict[str, dict] = {
    "momentum": {
        "id": "L1", "summary": "Cross-sectional momentum, the method behind NSE's Nifty200 Momentum 30 index. The most "
        "consistently documented stock-selection effect worldwide and in India.",
        "expect": "30-40% drawdowns and 1-2 years of lagging the market happen; the payoff comes in trending years.",
        "sources": [S("Jegadeesh & Titman (1993)"),
                    S("NSE research paper on momentum", "https://nsearchives.nseindia.com/content/research/res_paperfinal223.pdf"),
                    S("Nifty200 Momentum 30 whitepaper", "https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf")],
        "fails": ["Momentum crashes on sharp market reversals (Mar-Apr 2020, 2008-09).", "Sector concentration.",
                  "High turnover pushes gains into short-term capital gains tax (20.8%).",
                  "Crowding as momentum fund assets grow."],
    },
    "low_vol": {
        "id": "L2", "summary": "Low volatility (NSE Nifty100 Low Volatility 30 method). Strong evidence for smaller "
        "losses; the extra return is moderate and not significant after controlling for beta in India.",
        "expect": "Lags in strong bull runs; falls less in crashes (Mar 2020: about -31% vs -38% for Nifty 50).",
        "sources": [S("Ang, Hodrick, Xing & Zhang (2006)"), S("Frazzini & Pedersen (2014)"),
                    S("Joshipura et al. (IMFI 2020)", "https://www.businessperspectives.org/images/pdf/applications/publishing/templates/article/assets/13547/IMFI_2020_02_Joshipura.pdf"),
                    S("NSE methodology", "https://archives.nseindia.com/content/indices/Method_Nifty100_Low_Volatility_30.pdf")],
        "fails": ["Lags in strong bull runs.", "Tilts toward FMCG, pharma and IT.",
                  "Exposed to interest-rate moves and valuation crowding."],
    },
    "index_trend": {
        "id": "L3", "summary": "Index trend timing (Faber / 200-day average) on a Nifty ETF. The reliable benefit is a "
        "smaller drawdown, not a higher return.",
        "expect": "Similar long-run return to buy-and-hold with smaller crashes; whipsaw losses in sideways years.",
        "sources": [S("Faber (2007), SSRN 962461", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461"),
                    S("Brock, Lakonishok & LeBaron (1992)", "https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html"),
                    S("Against: Sullivan, Timmermann & White (1999)", "https://www.fmg.ac.uk/sites/default/files/2020-11/dp303.pdf")],
        "fails": ["Whipsaws in sideways years.", "V-shaped recoveries (2020).", "Tax on every switch.",
                  "A monthly check misses crashes inside a month."],
    },
    "dual_momentum": {
        "id": "L4", "summary": "Dual momentum across ETFs (relative + absolute momentum, Antonacci). Moderate evidence; "
        "the author's tests are largely in-sample.",
        "expect": "Very few switches, so results are noisy and depend on the lookback.",
        "sources": [S("Antonacci (2012), SSRN 2042750", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750"),
                    S("Moskowitz, Ooi & Pedersen (2012), time-series momentum")],
        "fails": ["Few switches: noisy.", "Sensitive to the lookback.", "Gold ETF premium/tracking error and different tax."],
    },
    "sector_rotation": {
        "id": "S7", "summary": "Industry momentum: hold the strongest stocks inside the strongest industries "
        "(Moskowitz & Grinblatt 1999). No strong India-specific study found.",
        "expect": "Large swings when sector leadership flips; concentrated in a few industries at a time.",
        "sources": [S("Moskowitz & Grinblatt (1999)", "https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html"),
                    S("Disputed: Grundy & Martin (2001)")],
        "fails": ["Industries with few, concentrated members.", "Reversals when leadership flips."],
    },
    "golden_cross": {
        "id": "S11", "summary": "Golden cross on single stocks. Weak evidence: moving-average rules did not survive "
        "out-of-sample tests (Sullivan, Timmermann & White).",
        "expect": "Slow; many small losses and a few big winners.",
        "sources": [S("Brock, Lakonishok & LeBaron (1992)"), S("Sullivan, Timmermann & White (1999)")],
        "fails": ["Lags badly at turning points.", "Whipsaws in sideways markets."],
    },
    "trend_breakout": {
        "id": "S1", "summary": "Minervini SEPA trend template + breakout. Practitioner evidence only (self-reported "
        "contest results); the trend parts overlap momentum and the 52-week-high effect.",
        "expect": "Many failed breakouts in choppy markets; a few large winners carry the results.",
        "sources": [S("Minervini (2013), Trade Like a Stock Market Wizard")],
        "fails": ["Breakouts fail often in choppy markets.", "Results-day gaps jump past stops.",
                  "Many parameters invite overfitting."],
    },
    "vcp_breakout": {
        "id": "S1", "summary": "Volatility contraction (VCP / Darvas box) breakout. Practitioner and folklore evidence; "
        "a 52-week-high breakout variant.",
        "expect": "Long quiet stretches with few signals; frequent small stop-outs.",
        "sources": [S("Minervini (2013)"), S("Darvas (1960), How I Made $2,000,000 in the Stock Market")],
        "fails": ["Breakouts fail often in choppy markets.", "Few signals: results are noisy."],
    },
    "donchian": {
        "id": "S3", "summary": "Turtle / Donchian channel breakout. Moderate evidence for diversified futures, weak for "
        "single stocks.",
        "expect": "Win rate around 30-40%, long flat stretches, whipsaw costs.",
        "sources": [S("Hurst, Ooi & Pedersen (2017)"), S("Moskowitz, Ooi & Pedersen (2012)")],
        "fails": ["Whipsaws in sideways markets.", "Trading-range breaks on stocks do not hold out of sample (STW 1999)."],
    },
    "pullback_leaders": {
        "id": "S5", "summary": "Pullback to the 21-day EMA in relative-strength leaders: momentum (strong) combined with "
        "short-term reversal, whose gross profits mostly vanish after costs.",
        "expect": "Small average gains per trade; Indian delivery costs (0.25-0.4% per round trip) are the main obstacle.",
        "sources": [S("Jegadeesh (1990), short-term reversal"), S("Avramov, Chordia & Goyal (2006)")],
        "fails": ["Costs eat the small edge.", "Pullbacks turn into trend changes in bear markets."],
    },
    "earnings_gap": {
        "id": "S6", "summary": "Post-earnings-announcement drift after a results-day gap. Strong in the US historically "
        "but fading; mixed evidence in India.",
        "expect": "Activity clusters in results seasons; many quiet weeks in between.",
        "sources": [S("Ball & Brown (1968)"), S("Bernard & Thomas (1989)"),
                    S("IIMB study (India)", "https://repository.iimb.ac.in/handle/2074/20501"),
                    S("Gupta & Dhusia (2021): no drift", "https://journals.vutbr.cz/index.php/trends/article/view/541")],
        "fails": ["Errors in the results-date proxy.", "Drift is weaker in large caps.",
                  "Overlapping results seasons crowd capacity."],
    },
    "bb_squeeze": {
        "id": "S8", "summary": "Bollinger squeeze breakout. Folklore: volatility does mean-revert, but nothing predicts "
        "the direction of the breakout.",
        "expect": "Frequent false breakouts.",
        "sources": [S("Bollinger (2001), Bollinger on Bollinger Bands")],
        "fails": ["No directional edge.", "False breakouts in ranges."],
    },
    "nr7_breakout": {
        "id": "S9", "summary": "NR7 narrow-range breakout (Crabel 1990). Folklore evidence.",
        "expect": "Many short trades; costs matter a lot.",
        "sources": [S("Crabel (1990)"), S("Connors & Raschke (1995)")],
        "fails": ["Short holding periods make costs dominate.", "No published out-of-sample evidence."],
    },
    "rsi2_pullback": {
        "id": "S10", "summary": "Connors RSI(2) pullback. Largely in-sample evidence from US large caps.",
        "expect": "Average gain per trade is smaller than Indian delivery costs.",
        "sources": [S("Connors & Alvarez (2009)"),
                    S("Community test (mostly unprofitable)", "https://prorealcode.com/prorealtime-trading-strategies/rsi-2p-larry-connors")],
        "fails": ["STT of 0.1% on each side exceeds the average edge."],
    },
    "near_high": {
        "id": "S4", "summary": "Nearness to the 52-week high (George & Hwang 2004): a documented effect, but our rank "
        "version never beat the average stock.",
        "expect": "Overlaps momentum; no extra edge in our tests.",
        "sources": [S("George & Hwang (2004)")],
        "fails": ["Contrary results for emerging-market indices."],
    },
    "legacy_rules": {
        "id": None, "summary": "The v1 textbook rules (50-DMA volume breakout, 52-week-high breakout). Kept only as a "
        "'what not to do' baseline.",
        "expect": "Loses money after costs.",
        "sources": [], "fails": ["Fixed small target/stop ratio with costs on every trade."],
    },
}

# Catalogue entries tested and rejected (fallback rows when the scan has no B4 metrics yet).
REJECTED_CATALOGUE = [
    {"key": "rsi2_pullback", "name": "RSI-2 pullback (Connors)", "horizon": "swing", "evidence": "WEAK",
     "result_text": "Lost money after realistic Indian delivery costs."},
    {"key": "legacy_rules", "name": "Old textbook rules (baseline)", "horizon": "swing", "evidence": "EXPERIMENTAL",
     "result_text": "About -12%/yr in testing."},
    {"key": "near_high", "name": "Near 52-week high", "horizon": "longterm", "evidence": "MODERATE",
     "result_text": "Never beat the average stock in our tests."},
]

_ENTRY = {
    "momentum": "Rank stocks by an NSE-style momentum score (6- and 12-month return divided by volatility, z-scored){uptrend}.",
    "low_vol": "Rank the {universe_size} most traded stocks by 1-year volatility, lowest first.",
    "sector_rotation": "Find the {top_industries} strongest industries (average 6-month return of their stocks); rank their stocks above the 200-day average by relative strength.",
    "index_trend": "Hold the {etf} ETF while Nifty 50 is above its 200-day average; otherwise hold cash (earning the Nifty 1D rate).",
    "dual_momentum": "Rank the ETFs {etfs} by 12-month return; only ETFs with a positive 12-month return qualify, otherwise cash.",
    "golden_cross": "Buy when the 50-day average crosses above the 200-day average in a stock with relative strength {rs_min}+.",
    "trend_breakout": "Buy a stock in a strong uptrend (above rising 50/150/200-day averages, near its high, relative strength {rs_min}+) closing above its 20-day high on {min_vol_ratio}x volume.",
    "vcp_breakout": "Buy a leader near its 52-week high breaking out of a tight 15-day box (under {max_box_pct}% high-to-low) on {min_vol_ratio}x volume.",
    "donchian": "Buy a close above the previous 55-day high in a stock above its 200-day average.",
    "pullback_leaders": "Buy a relative-strength leader (RS {rs_min}+) in a stage-2 uptrend when the day's low touches the 21-day EMA and the close stays above it.",
    "earnings_gap": "Within 2 days of quarterly results, buy a stock that gaps up {min_gap_pct}%+ on {min_vol_ratio}x volume and holds the gap, above its 200-day average.",
    "bb_squeeze": "Buy the first close above the upper Bollinger Band after the bands were at their narrowest in 6 months, in an uptrend.",
    "nr7_breakout": "After the narrowest-range day in 7 sessions, buy a close above that day's high in an uptrending leader (RS 70+).",
    "rsi2_pullback": "Buy when RSI(2) falls below {rsi2_below} in a stock above its 200-day average.",
    "near_high": "Rank uptrending stocks by distance to their 52-week high, closest first.",
    "legacy_rules": "Buy a 50-day-average volume breakout or a 52-week-high breakout.",
}
_EXIT_SIGNAL = {
    "golden_cross": "Exit when the 50-day average falls back below the 200-day average (death cross).",
    "trend_breakout": "Exit on a close below the 50-day average.",
    "vcp_breakout": "Exit on a close below the 50-day average.",
    "donchian": "Exit on a close below the previous 20-day low.",
    "pullback_leaders": "Exit on a close below the 50-day average.",
    "earnings_gap": "Exit on a close below the 50-day average.",
    "bb_squeeze": "Exit on a close below the 20-day average.",
    "nr7_breakout": "Exit on a close below the 10-day average.",
    "rsi2_pullback": "Exit when the close rises above the 5-day average.",
}
_DEFAULTS = {"uptrend": True, "universe_size": 150, "top_industries": 3, "etf": "NIFTYBEES",
             "etfs": "NIFTYBEES, JUNIORBEES, BANKBEES, GOLDBEES, MON100", "rs_min": None, "min_vol_ratio": None,
             "max_box_pct": 12, "min_gap_pct": 4, "rsi2_below": 10}
_RS_DEFAULT = {"golden_cross": 60, "trend_breakout": 90, "vcp_breakout": 80, "pullback_leaders": 80}
_VOL_DEFAULT = {"trend_breakout": 2.0, "vcp_breakout": 1.5, "earnings_gap": 3}


def evidence_card(key: str, grade: str) -> dict:
    c = CATALOG.get(key)
    if not c:
        return {"grade": grade, "catalogue_id": None, "summary": "No catalogue entry for this strategy yet.",
                "what_to_expect": "Judge it only by its edge versus the average stock and the Nifty 500.",
                "sources": [], "failure_modes": [], "validation": None}
    return {"grade": grade, "catalogue_id": c["id"], "summary": c["summary"], "what_to_expect": c["expect"],
            "sources": c["sources"], "failure_modes": c["fails"], "validation": None}


def plain_rules(key: str, rules: dict) -> list[str]:
    params = dict(_DEFAULTS)
    params["rs_min"] = _RS_DEFAULT.get(key)
    params["min_vol_ratio"] = _VOL_DEFAULT.get(key)
    for k, v in (rules.get("params") or {}).items():
        params[k] = ", ".join(map(str, v)) if isinstance(v, list) else v
    params["uptrend"] = " (only stocks above their 200-day average)" if params.get("require_uptrend", True) else ""
    out = []
    try:
        out.append(_ENTRY[key].format(**params))
    except (KeyError, IndexError, ValueError):
        if key in _ENTRY:
            out.append(_ENTRY[key])
    if rules.get("kind") == "rank":
        out.append(f"Hold the top {rules.get('top_n')}; keep a holding while it ranks within the top "
                   f"{rules.get('keep_rank') or rules.get('top_n')}. Reviewed {rules.get('rebalance') or 'monthly'}, "
                   "decided at the close and traded at the next open.")
    else:
        out.append(f"Signals are read at the close and filled at the next open; up to {rules.get('max_positions')} "
                   "positions at a time.")
        if key in _EXIT_SIGNAL:
            out.append(_EXIT_SIGNAL[key])
    if rules.get("stop_pct"):
        out.append(f"Stop-loss {rules['stop_pct']:g}% below the fill price (checked against each day's low).")
    if rules.get("stop_atr"):
        out.append(f"Initial stop {rules['stop_atr']:g} x ATR(14) below the fill price.")
    if rules.get("target_pct"):
        out.append(f"Profit target {rules['target_pct']:g}% above the fill price.")
    if rules.get("trail_pct"):
        out.append(f"Trailing stop {rules['trail_pct']:g}% below the highest close since entry.")
    if rules.get("max_hold"):
        out.append(f"Time limit: sell after {rules['max_hold']} trading days.")
    if rules.get("sizing") == "risk" and rules.get("risk_pct"):
        out.append(f"Position size: risk {rules['risk_pct']:g}% of equity if the stop is hit (at most 2x an equal slot).")
    else:
        out.append(f"Equal weight: capital / {rules.get('max_positions')} per position.")
    if rules.get("use_regime"):
        action = ("sells everything" if rules.get("regime_action") == "cash" else "makes no new buys")
        out.append(f"Regime filter: while Nifty 50 is below its 200-day average the strategy {action}.")
    out.append("Every order pays full Indian delivery charges plus slippage (0.10% liquid, 0.25% illiquid stocks).")
    return out
