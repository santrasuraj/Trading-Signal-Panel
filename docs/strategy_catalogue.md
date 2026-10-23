# NSE Strategy Catalogue: Intraday, Swing and Long-Term

*Prepared 2026-10-23 for the FYERS / Nifty-500 research platform (v2 codebase at `D:\New folder\stock_scanner`, read-only). Scratch work, including the parsed SEBI study and NSE file samples, is in `C:\Users\suraj\AppData\Local\Temp\claude\D--New-folder\8c8a39c7-06d8-4ca7-a5b2-5aeda1a9ef1f\scratchpad\strategy-catalogue\`.*

**Evidence grades.** STRONG = peer-reviewed, replicated, has an out-of-sample or live record, and has Indian evidence. MODERATE = peer-reviewed abroad, with mixed or thin Indian evidence, or a live index record only. WEAK = working papers, the author's own backtests, or one market only. FOLKLORE = practitioner books or forums with no systematic test.

**Data codes.**
- **D**: daily OHLCV in the store (2018-08 onward).
- **X**: other free NSE daily files the code already downloads or can download. `ind_close_all` has about 170 indices, including all sector indices, the NSE factor indices and *Nifty 1D Rate*. The stock bhavcopy includes ETFs (NIFTYBEES, GOLDBEES, LIQUIDBEES and BANKBEES were confirmed in the cached files). The `PR{ddmmyy}.zip` file contains `bm` (board meetings / results dates), `an` (announcements), `bc` (book closures, including dividends) and `mcap` (daily market cap per stock). All four were checked in PR221026.zip.
- **I**: 1-min or 5-min bars from FYERS. On the Standard plan this is about 1 rolling year, at most 100 days per request.
- **F**: point-in-time fundamentals. **We do not have these.**
- **E**: event dates, from the `bm`/`an` archive.

---

## 1. Summary table

| # | Strategy | Horizon | Evidence | Data | Supported today? | Verdict |
|---|---|---|---|---|---|---|
| L1 | Cross-sectional momentum (NSE Nifty200 Momentum 30 method) | Long | STRONG | D | Yes (already primary) | **IMPLEMENT** (check against the stored NSE index) |
| L2 | Low volatility (NSE Nifty100 LowVol 30 method) | Long | MODERATE (STRONG for lower drawdowns) | D | Yes (already exists) | **IMPLEMENT** |
| L3 | Index trend timing: Faber 10-month SMA / 200-DMA / golden cross on Nifty via NIFTYBEES | Long | MODERATE (cuts drawdowns; does not reliably add return) | D+X | Yes, after adding the ETF series and the 1D-rate cash series | **IMPLEMENT** |
| L4 | Dual momentum: NIFTYBEES vs GOLDBEES vs cash | Long | MODERATE | X | Yes, after adding ETFs | **IMPLEMENT** |
| L5 | Equal-weight Nifty 50, annual rebalance | Long | MODERATE | D + point-in-time constituents | Partly (constituents come from the survivorship session) | **IMPLEMENT** (plus NSE EW index as a benchmark) |
| L6 | Quality (stock-level) | Long | STRONG globally, MODERATE in India | F | No | **SKIP-NO-DATA** (stock level); **IMPLEMENT** an index proxy (Nifty200 Quality 30) |
| L7 | Value / low P/E (stock-level) | Long | STRONG globally, MODERATE in India | F | No | **SKIP-NO-DATA** (stock level); **IMPLEMENT** an index proxy (Nifty200 Value 30, Nifty500 Value 50) |
| L8 | Dividend yield | Long | WEAK to MODERATE | D + X (dividends from `bc`) | Yes, after parsing dividends | **IMPLEMENT-AS-EXPERIMENTAL** (plus index proxies) |
| L9 | "Coffee can" buy-and-hold quality | Long | WEAK | F (10 years) | No; also needs a test horizon longer than our data | **SKIP-NO-DATA** |
| L10 | Momentum + low-vol 50/50 blend | Long | MODERATE | D | Yes | **IMPLEMENT** |
| S1 | Minervini SEPA trend template + VCP | Swing | WEAK | D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** (extends `trend_breakout`) |
| S2 | Darvas box | Swing | FOLKLORE | D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| S3 | Turtle / Donchian 20/55 | Swing | MODERATE for futures, WEAK for single stocks | D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| S4 | O'Neil 52-week-high breakout on volume | Swing | MODERATE for the 52-week-high effect, WEAK for the rule itself | D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** (`near_high` already failed once) |
| S5 | Pullback to 20/50 EMA in RS leaders | Swing | WEAK | D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| S6 | Post-earnings drift / earnings-gap continuation | Swing | MODERATE (strong in the US but fading; mixed in India) | D+E | Yes, once the `bm` archive is loaded | **IMPLEMENT-AS-EXPERIMENTAL** (promote if it holds out-of-sample) |
| S7 | Sector rotation (NSE sector indices) | Swing / long | MODERATE | X | Yes (all sector indices are in the daily file) | **IMPLEMENT** |
| S8 | Bollinger squeeze | Swing | FOLKLORE | D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| S9 | NR7 / inside day | Swing (or intraday) | FOLKLORE | D (I for the intraday version) | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| S10 | Connors RSI(2) / cumulative RSI | Swing | WEAK (and already failed here) | D | Yes | **SKIP-NO-EVIDENCE** (show in a "tested and rejected" list) |
| S11 | Golden cross on single stocks | Swing | WEAK | D | Yes | **SKIP-NO-EVIDENCE** (index version is kept inside L3) |
| S12 | 52-week-low mean reversion | Swing | Evidence against | D | Yes | **SKIP-NO-EVIDENCE** (optional negative control on the survivorship-free universe) |
| I1 | Opening Range Breakout 5/15/30/60 min, including first-hour high/low and opening drive | Intraday | WEAK to MODERATE (US working papers; none for India) | I | Yes (about 1 year) | **IMPLEMENT-AS-EXPERIMENTAL** |
| I2 | VWAP trend (long above, short below) | Intraday | WEAK | I | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| I3 | VWAP pullback and VWAP reversion | Intraday | FOLKLORE / WEAK | I | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| I4 | Gap-and-go vs gap fade | Intraday | WEAK to MODERATE (fade of attention gaps) | I+E | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| I5 | Intraday momentum (first 30 min predicts last 30 min; Gao, Han, Li, Zhou 2018) | Intraday | MODERATE globally; no Indian study found | I | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| I6 | CPR / Camarilla / floor pivots | Intraday | FOLKLORE | I | Yes | **IMPLEMENT-AS-EXPERIMENTAL** (textbook settings only, no tuning) |
| I7 | Supertrend | Intraday / swing | FOLKLORE | I / D | Yes | **IMPLEMENT-AS-EXPERIMENTAL** |
| I8 | Closing-hour trend | Intraday | MODERATE (index), WEAK (stocks) | I | Yes, but the MIS 15:05 cutoff limits it | **IMPLEMENT-AS-EXPERIMENTAL** (same family as I5) |

Two structural facts limit every intraday card. Both are new as of 2026:

1. **NSE Closing Auction Session (CAS).** It went live on **3 Aug 2026** for F&O stocks. Continuous trading moves to a transition at 15:15 and the closing price is now set by auction, no longer by a VWAP.
2. **FYERS MIS auto square-off times.** FYERS squares off intraday positions at **15:05 for CAS-eligible (F&O) stocks** and at **15:20 for non-F&O stocks**. After 15:05 only CNC orders are allowed in F&O stocks. An auto square-off costs ₹50 + GST per order.

So the real "last half hour" for an MIS trade in an F&O stock is about 14:35 to 15:05. The one year of FYERS intraday history covers both the old and the new closing regime.

---

## 2. What our data can and cannot do

- **Have now (D):** about 500 Nifty-500 stocks with daily OHLCV from 2018-08, adjusted for splits and bonuses only (dividends are not adjusted). The store keeps only the NIFTY50, INDIAVIX and NIFTY500 index columns.
- **Free, needs a loader (X).** All of these come from the NSE archive the code already uses.
  - Sector indices: Nifty Bank, IT, Pharma, FMCG, Auto, Metal, Energy, Realty, PSU Bank, Media, Financial Services, Infrastructure, Commodities, India Consumption, Healthcare, Oil & Gas and others.
  - NSE factor indices, usable as benchmarks and as "investable proxies": Nifty200 Momentum 30, Nifty100 Low Volatility 30, NIFTY100/200 Quality 30, Nifty200 Value 30, NIFTY500 Value 50, Nifty50 Value 20, NIFTY50 Equal Weight, Nifty100 Equal Weight, Nifty Dividend Opportunities 50, Nifty High Dividend Yield 15, Nifty Alpha 50 and Nifty Alpha Low-Volatility 30.
  - **Nifty 1D Rate Index**, which is the correct cash-return series.
  - ETFs in the bhavcopy.
  - PR zip files: `bm` (results meeting dates, point-in-time), `an`, `bc` (dividend text) and `mcap` (daily market cap, which also helps the survivorship-free universe).
- **LIQUIDBEES pitfall.** Its price is pinned near ₹1000. The return is paid as daily dividends that are reinvested as extra units, so the price series shows roughly zero return. Never backtest cash using LIQUIDBEES prices; use Nifty 1D Rate. Dividends are taxed at the investor's slab rate. Sources: [tradingqna](https://tradingqna.com/t/why-liquidbees-value-doesnt-vary-from-1000-in-spite-of-having-good-volumes-on-this-etf/19), [PersonalFN factsheet](https://www.personalfn.com/factsheet/nippon-india-etf-liquid-bees).
- **Intraday (I).** On the Standard plan FYERS gives about 1 year of rolling intraday history ([Plans & Limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)), at most 100 days per request for 1–240 min resolutions ([forum](https://fyers.in/community/fyers-api-rha0riqv/post/limit-in-history-SyjytuRSpdWwNBd)). Rate limits are 5 requests/s, 50/min and 5,000/day.
  - About 200 F&O stocks × 4 requests ≈ 800 requests, roughly 16 minutes.
  - **Fetch 1-min, not 5-min.** It costs the same number of requests and settles which of the stop or target was hit first inside a bar. Resample to 5-min.
  - **Start a daily archiving job now**, because the 1-year window rolls forward and old data is lost.
  - yfinance only gives 60 days of 5-min data, so it is not useful here.
- **Fundamentals (F).** No free point-in-time source is clean.
  - NSE and BSE XBRL result filings are free and point-in-time (they carry a filing timestamp) but are heavy to parse.
  - screener.in needs a login and its terms restrict scraping.
  - yfinance `.NS` fundamentals cover about 4 years, are not point-in-time and have gaps.
  - The [IIMA factor library](https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/) gives factor *returns* (SMB, HML, WML), not stock data. It is useful as an outside check.
- **Results calendar.** `scanner/events.py` today only fetches the next 3 weeks of results. The history has to be rebuilt from the archived `bm` files: one PR zip per trading day, each listing announced future meetings.

---

## 3. Cost and tax models

### 3a. Intraday equity (MIS), FYERS Standard. Source: [FYERS charges list](https://fyers.in/charges-list.md)

For a round trip with buy value B and sell value S (this also applies to shorts: sell first, then buy back):

```
brokerage = min(20, 0.0003*B) + min(20, 0.0003*S)      # Rs 20 or 0.03% per executed order, whichever lower (Prime: Rs 15)
stt       = 0.00025 * S                                 # 0.025% on SELL side only
exch      = 0.000030699 * (B + S)                       # NSE txn charge as billed by FYERS (0.00297% NSE + IPFT ~= 0.00307%)
sebi      = 0.000001 * (B + S)                          # Rs 10 per crore
stamp     = 0.00003 * B                                 # 0.003% on BUY side only
gst       = 0.18 * (brokerage + exch + sebi)            # GST 18% (not on STT or stamp)
admin_sq  = 59 per order if RMS auto-squares (Rs 50 + GST)
```

Worked examples, statutory charges plus brokerage, before slippage:

| Round trip | Cost | % of one side |
|---|---|---|
| ₹25,000 | ₹26.6 | 0.106% |
| ₹1,00,000 | ₹82.7 | 0.083% |
| ₹5,00,000 | ₹224.6 | 0.045% |

On top of that, model slippage per side: about 0.03% for Nifty-50 stocks, 0.07% for other F&O stocks, and 0.05–0.10% extra on stop-entry fills. A realistic all-in round trip is therefore about **0.15–0.30%**. Many intraday edges in the literature are smaller than this.

NSE's 0.00297% rate (slabs ended 1 Oct 2024) is from [Zerodha](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/why-am-i-being-charged-higher-transaction-charges); FYERS bills 0.0030699%, which is why `config.yaml` uses 0.00307. The ₹20 / 0.03% brokerage is on the [FYERS pricing page](https://fyers.in/pricing.md).

**MIS timing.** FYERS auto square-off is 15:05 for CAS-eligible (F&O) stocks and 15:20 for non-F&O stocks ([FYERS support](https://support.fyers.in/portal/en/kb/articles/what-is-the-intraday-square-off-timings-at-fyers)). Backtests should force exits at **15:00 for F&O stocks** and **15:15 for non-F&O stocks and ETFs** such as NIFTYBEES.

**Tax.** Intraday equity profit is *speculative business income*, taxed at the slab rate (make it a config value, e.g. 31.2%). Speculative losses can only be set off against speculative income, carried forward 4 years. Do **not** use the STCG 20.8% model for intraday.

### 3b. Delivery (existing `costs:` block, matches FYERS)

Brokerage min(₹20, 0.3%), STT 0.1% on both sides, stamp 0.015% on buys, exchange 0.00307%, SEBI fee, 18% GST, and a DP charge of ₹14.75 per scrip per sell day.

For ETFs (L3, L4, S7), add an asset-class cost profile. STT on equity-ETF units is 0.001% on the sell side only, and non-equity ETFs (gold, liquid) are believed to carry no STT; **verify both on a real contract note**. Gold ETF tax is different from equity. The current understanding is LTCG 12.5% if held more than 12 months and slab rate otherwise; **verify this**.

### 3c. SEBI evidence on retail intraday traders

From [SEBI, *Analysis of Intraday trading by Individuals in Equity Cash Segment*, July 2024](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf). I parsed the PDF directly.

- **71%** of individual intraday traders made net losses in FY23, up from 65% in FY19 and 69% in FY22.
- **80%** of those making more than 500 trades a year lost money.
- **76%** of traders under 30 lost money.
- Even among traders active in all three years, **54%** lost money.
- **76%** of traders with intraday turnover above ₹1 crore lost money; that group's average P&L was −₹34,977.
- Trading costs **made loss-makers' trading losses 57% larger**, and **took 19% of profit-makers' trading profits**.
- The top 6% of traders account for more than 90% of turnover.

Coverage: [Business Standard](https://www.business-standard.com/markets/news/over-70-intra-day-traders-incur-losses-during-fy23-reveals-sebi-study-124072401110_1.html).

For F&O, **93%** of individual traders lost money over FY22–FY24, more than **₹1.8 lakh crore** in total ([SEBI PR, Sep 2024](https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html)).

From memory, not re-fetched: Barber, Lee, Liu and Odean found that under 1% of Taiwanese day traders are predictably profitable after fees, and Chague, De-Losso and Giovannetti (2019) found that 97% of Brazilian day traders who kept going for more than 300 days lost money. **Suggested UI use:** put these numbers on the intraday tab.

---

## 4. Rule cards: long-term

Shared defaults for long-term cards:
- Signals are computed on the close of day t and filled at the open of t+1. The engine already supports this.
- Use the delivery cost model and after-tax equity.
- Report timing-luck ranges (rebalance offsets).

### L1. Cross-sectional momentum (NSE method)

**Horizon:** long-term (monthly or semi-annual). **Grade:** STRONG. **Data:** D. **Verdict:** IMPLEMENT (already primary).

- **Universe:** a point-in-time Nifty 200. Until the survivorship session delivers constituents, approximate it as the top 200 by 6-month average market cap from `mcap`. Require at least 252 days of listing. F&O availability is an optional filter (the NSE index requires it).
- **Score (NSE):**
  - σ = standard deviation of daily log returns over 252 days.
  - MR6 = ret126 / σ and MR12 = ret252 / σ.
  - Take cross-sectional z-scores (winsorise at ±3): wZ = 0.5·Z6 + 0.5·Z12.
  - Normalised score NMS = 1 + wZ if wZ ≥ 0, else 1 / (1 − wZ).
  - Make `skip_days` ∈ {0, 21} a parameter. The academic standard is "12-1" (skip the latest month). NSE's whitepaper does not say whether it skips a month.
- **Selection and weights:** top N. NSE uses 30; retail can use 15. Buffer: keep a holding while its rank ≤ 2N (the engine's `keep_rank`). Weight equally (recommended), or NMS × market cap capped at 5% (NSE).
- **Rebalance:** semi-annual in June and December (NSE) vs monthly. Test both, with the tax drag shown.
- **Optional regime filter:** no new buys while Nifty 50 < its 200-DMA (existing `regime_action: hold`).
- **Correctness test:** replicate the stored *Nifty200 Momentum 30* price index. Low tracking error shows the implementation is right.
- **Evidence:**
  - Jegadeesh and Titman (1993).
  - India: [NSE research paper](https://nsearchives.nseindia.com/content/research/res_paperfinal223.pdf) and [NSE RP 2, Feb 2012](https://nsearchives.nseindia.com/research/content/RP_2_Feb2012.pdf). The latter reports short-term momentum followed by long-term reversal, and about 12% a year from 6/6 momentum.
  - The IIMA WML factor.
  - The NSE whitepaper backtest from Apr 2005 shows 18.6% CAGR vs 12.7% for the Nifty 200, with volatility of 23.4% vs 22.3% ([whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf), [factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf), [method explainer](https://freefincal.com/nifty200-momentum-30-index-a-new-strategy-index-from-the-nse/)).
  - The index has been live since Aug 2020, which is genuinely out-of-sample.
- **Failure modes:**
  - Momentum crashes on sharp market reversals (Daniel and Moskowitz 2016; Mar–Apr 2020). Measure the late-2024 to 2025 Indian momentum drawdown from the stored index.
  - Sector concentration.
  - Turnover pushes gains into STCG at 20.8%.
  - Crowding as momentum fund assets grow.
- **Data today:** yes.

### L2. Low volatility (NSE method)

**Horizon:** long-term (quarterly). **Grade:** MODERATE for excess return, STRONG for risk reduction. **Data:** D. **Verdict:** IMPLEMENT.

- **Universe:** a point-in-time Nifty 100 (proxy: top 100 by market cap), at least 1 year listed, F&O optional.
- **Score:** σ = standard deviation of daily log returns over 252 days. Rank ascending and take the top 30. Keep an existing holding while it ranks in the top 60 (NSE's buffer).
- **Weights:** w ∝ 1/σ (NSE), with a 3% cap on the least liquid names. Equal weight is an option.
- **Rebalance:** quarterly.
- **Correctness test:** replicate the stored *Nifty100 Low Volatility 30* index.
- **Evidence:**
  - Abroad: Ang, Hodrick, Xing and Zhang (2006), Baker, Bradley and Wurgler (2011), Frazzini and Pedersen (2014).
  - India, Joshipura et al.: the low-vol decile earned 11.4% a year vs 1.3% for the high-vol decile over 2001–2015, though this was not significant after controlling for beta ([AFL](https://ojs.aut.ac.nz/applied-finance-letters/article/download/32/31)); the effect holds independently of size, value and momentum on the top 500 NSE stocks over 2004–2018 ([IMFI 2020](https://www.businessperspectives.org/images/pdf/applications/publishing/templates/article/assets/13547/IMFI_2020_02_Joshipura.pdf)).
  - [NSE methodology](https://archives.nseindia.com/content/indices/Method_Nifty100_Low_Volatility_30.pdf).
- **Failure modes:**
  - Lags in strong bull runs.
  - Tilts toward FMCG, pharma and IT.
  - Exposed to interest-rate moves and valuation crowding.
  - In Mar 2020 it fell about 31% vs 38% for the Nifty 50: it lowers drawdowns but does not remove them.

### L3. Index trend timing (Faber 10-month SMA / 200-DMA / golden cross)

**Horizon:** long-term (monthly check). **Grade:** MODERATE. **Data:** D+X. **Verdict:** IMPLEMENT, both as an allocation overlay and as the platform's "market regime" light.

- **Instruments:** NIFTYBEES (risk-on) and cash. Use the *Nifty 1D Rate* index for the cash return; in live trading the cash is LIQUIDBEES.
- **Rule A (Faber):** on the last trading day of the month, hold NIFTYBEES next month if the Nifty 50 close is above the 10-month SMA of month-end closes; otherwise hold cash.
- **Rule B (200-DMA with a band):** go long when close > 1.02 × SMA200 and go to cash when close < 0.98 × SMA200, evaluated weekly to cut whipsaws.
- **Rule C (golden cross):** long while SMA50 > SMA200. Report it only as a variant.
- **Execution:** next open. Costs are ETF delivery costs plus the capital-gains tax on each exit.
- **History:** extend the Nifty series back from NSE index archives (pre-2018) to cover 2008, 2011 and 2015–16. Eight years contain too few bear markets to judge.
- **Evidence:**
  - Faber (2007, Journal of Wealth Management; [SSRN 962461](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461), ID from memory), [Quantpedia summary](https://quantpedia.com/strategies/asset-class-trend-following).
  - Brock, Lakonishok and LeBaron (1992) ([RePEc](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html)).
  - Moskowitz, Ooi and Pedersen (2012) on time-series momentum.
  - **Against:** Sullivan, Timmermann and White (1999) find the best rule out-of-sample (1987–96) is not significant ([FMG DP303](https://www.fmg.ac.uk/sites/default/files/2020-11/dp303.pdf)).
  - Conclusion: the reliable benefit is a smaller drawdown, not a higher CAGR.
- **Failure modes:** whipsaws in sideways years; V-shaped recoveries (2020); tax on every switch; monthly checks miss crashes inside a month.

### L4. Dual momentum: Nifty vs Gold vs Cash

**Horizon:** long-term (monthly). **Grade:** MODERATE. **Data:** X. **Verdict:** IMPLEMENT.

- **Assets:** NIFTYBEES and GOLDBEES. JUNIORBEES and a G-Sec series (*Nifty 10 yr Benchmark G-Sec* is in the index file) are optional. Cash = Nifty 1D Rate.
- **Rule (month end):**
  - R12(a) = 12-month return of each asset, adjusting NIFTYBEES for its small dividends.
  - Relative step: pick argmax(R12) between equity and gold.
  - Absolute step: hold the pick if its R12 > R12(cash), otherwise hold cash or G-Sec.
  - Execute at the next open.
- **Variant:** average the 1-, 3-, 6- and 12-month lookbacks to reduce lookback luck.
- **Evidence:** Antonacci (2012, [SSRN 2042750](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750), ID from memory; 2014 book). The rule definitions are summarised [here](https://algoadvantage.substack.com/p/gary-antonacci-absolute-and-relative). The underlying support is time-series momentum (MOP 2012) and Asness, Moskowitz and Pedersen (2013). The author's tests are largely in-sample, so the grade is not STRONG.
- **Failure modes:**
  - Very few switches, so results are noisy.
  - Sensitive to the lookback.
  - GOLDBEES premium to NAV and tracking error.
  - Gold ETF tax is different from equity.
- **Data:** ETF history is in the bhavcopy; extend it back before 2018 from the archive.

### L5. Equal-weight Nifty 50

**Horizon:** long-term (annual; also test quarterly). **Grade:** MODERATE. **Data:** D + point-in-time constituents. **Verdict:** IMPLEMENT.

- **Rule:** hold every point-in-time Nifty 50 member at 2%. Rebalance each year in the first week of January, and also when membership changes.
- **Benchmarks:** compare with the stored *NIFTY50 Equal Weight* index (NSE rebalances it quarterly) and with the Nifty 50.
- **Evidence:** DeMiguel, Garlappi and Uppal (2009) on 1/N; Plyakha, Uppal and Vilkov (2012), who show the edge comes from size and value tilts plus rebalancing.
- **Failure modes:**
  - Lags when mega-caps lead.
  - 50 positions cost about ₹740 a year in DP charges at each annual sell.
  - **Survivorship:** using *today's* Nifty 50 for 2018 inflates results. Wait for the survivorship-free session's constituents.

### L6. Quality (stock level), with an index proxy

**Grade:** STRONG globally (Novy-Marx 2013; Asness, Frazzini and Pedersen's QMJ), MODERATE in India (NSE quality indices are live). **Data:** F. **Verdict:** SKIP-NO-DATA for the stock-level version; **IMPLEMENT the index proxy now.**

- **Stock-level rules (NSE Nifty200 Quality 30 style):** z-scores of ROE (high), debt/equity (low) and variability of 5-year EPS growth (low). Combine them, take the top 30, weight by score × market cap, rebalance semi-annually. Every input must be point-in-time: use financials only after their filing timestamp.
- **Index proxy:** show NIFTY100 Quality 30, Nifty200 Quality 30 and Nifty500 Quality 50 from the daily index file. They can be bought through index funds or ETFs.
- **Free fundamental sources:**
  - NSE/BSE XBRL filings: free and point-in-time, but a big parsing job.
  - screener.in: login and terms-of-service limits.
  - yfinance: not point-in-time; do not use it for backtests.

### L7. Value / low P/E, with an index proxy

**Grade:** STRONG globally (Basu 1977; Fama and French 1992), MODERATE in India. **Data:** F. **Verdict:** SKIP-NO-DATA for the stock-level version; **IMPLEMENT the index proxy.**

- **Stock-level rules (Nifty200 Value 30 style):** composite of E/P, B/P, S/P and D/P z-scores; top 30; semi-annual rebalance. Trailing EPS comes from the last four quarterly filings, each used only after its filing date.
- **Index proxy:** Nifty200 Value 30, NIFTY500 Value 50 and Nifty50 Value 20 (all in the daily file).
- **Indian evidence:**
  - A value premium over 1996–2010 ([IJAF 2012](https://ideas.repec.org/a/icf/icfjaf/v18y2012i2p48-62.html)).
  - A persistent premium over 1999–2017 that is largely explained by risk factors ([Inderscience](https://www.inderscience.com/filter.php?aid=120448)).
  - A low-P/E study on NSE over 1995–2017 ([NMIMS 2018](https://management-review.nmims.edu/docs/2018/April/Issue-1(4).pdf)).
  - A weaker industry-level premium in the last decade ([Christ Univ.](https://archives.christuniversity.in/items/show/15286)).
- **Optional experiment:** time the index on its P/E band. NSE publishes daily index P/E, P/B and dividend yield. Grade WEAK, because valuation predicts long-horizon returns but times entries poorly.

### L8. Dividend yield

**Grade:** WEAK to MODERATE. **Data:** D + X. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL, plus index proxies.

- **Point-in-time dividends:** parse `bc` PURPOSE text such as "DIVIDEND - RS x PER SHARE" at each ex-date. DY = trailing-12-month dividends / close.
- **Rule:**
  - Universe: liquid Nifty 500 names.
  - Eligibility: DY > 0 in each of the last 3 years, and 12-month return > −30% (screens out yield traps).
  - Take the top 30 by DY, equal-weighted, rebalanced semi-annually.
- **Index proxies:** Nifty Dividend Opportunities 50 and Nifty High Dividend Yield 15.
- **Caveats:** in India dividends are taxed at the slab rate, so DY strategies are worse after tax for high-slab investors. Model this. The engine currently ignores dividends, which biases all strategies slightly low; add a dividend total-return adjustment.

### L9. Coffee can

**Grade:** WEAK. **Data:** F (10+ years). **Verdict:** SKIP-NO-DATA.

- **Rules (Ambit):** revenue growth > 10% and ROCE > 15% over a 10–20-year record, then a buy-and-hold of up to about 20 stocks with very little churn ([Ambit factsheet, Aug 2026](https://www.ambit.co/wp-content/uploads/2026/08/Ambit-Coffee-Can-Portfolio-Factsheet_Aug_26.pdf)). The factsheets do not clearly say the thresholds must be met *every* year.
- **Why skip:** no point-in-time fundamentals; the holding period is longer than our data; screening today's survivors backward builds in heavy survivorship and hindsight; the evidence is the vendor's own track record. The quality index proxy (L6) is the honest stand-in.

### L10. Momentum + low-vol blend

**Grade:** MODERATE. **Data:** D. **Verdict:** IMPLEMENT.

- **Rule:** 50% in L1 and 50% in L2, rebalanced quarterly. Variant: a single combined score of 0.5·rank(momentum) + 0.5·rank(−σ).
- **Evidence:** Joshipura (2020) finds that adding momentum improves the low-risk strategy in India. NSE's Alpha Low-Volatility 30 index is stored as a benchmark.
- **Why it matters:** the two factors are negatively correlated in crashes, which smooths L1's drawdowns.

---

## 5. Rule cards: swing

Shared defaults for swing cards:
- Daily bars. Universe = liquid Nifty 500 (turnover ≥ ₹25 crore a day, price ≥ ₹50).
- Long-only, because overnight shorting is not possible in the cash market.
- Entry uses either (a) a signal at close with a fill at the next open, or (b) a stop order at level L, filled at max(open, L) if high ≥ L. Option (b) needs a small engine addition.
- If the stop and target are both touched in one daily bar, assume the stop was hit first.
- Sizing: risk 0.75% of equity per trade, shares = 0.0075·E / (entry − stop), capped at 15% of equity per position and 10 positions.
- Delivery costs plus STCG.
- Minimum 100 trades before giving any verdict.

### S1. Minervini SEPA / VCP

**Grade:** WEAK. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Trend template (already in `_trend_template`):** C > SMA50 > SMA150 > SMA200; SMA200 rising for at least 21 days; C ≥ 1.30 × 52-week low; C ≥ 0.75 × 52-week high; RS rating ≥ 70 (test 70 and 90).
- **VCP approximation:**
  - Over the last 30–65 days, find swing highs and lows with a 5% zigzag.
  - Require at least 2 successive pullbacks, each shallower than the last (e.g. ≤ 25%, then ≤ 15%, then ≤ 8%).
  - The final contraction is ≤ 10% deep.
  - Volume dries up: 10-day average volume < 0.7 × 50-day average.
  - Pivot = high of the final contraction.
- **Entry:** buy-stop at 1.001 × pivot, valid only if that day's volume ≥ 1.5 × the 50-day average. Confirm at the close (no volume check is possible intraday on daily bars) and fill at the next open.
- **Stop:** the tighter of the final-contraction low or −8%.
- **Exit:** close < SMA50, or a 3×ATR trailing stop after +2R. Optional: sell half at +20%.
- **Evidence:** practitioner only (Minervini 2013; his contest results are self-reported). The trend parts overlap momentum and the 52-week-high effect.
- **Failure modes:** breakouts fail often in choppy markets; gaps on results days jump past stops; many parameters invite overfitting.

### S2. Darvas box

**Grade:** FOLKLORE. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Box top:** a new 52-week high H, followed by 3 consecutive sessions with high < H.
- **Box bottom:** the lowest low after the top is set, confirmed by 3 sessions with low > that level.
- **Entry:** buy-stop at the box top on volume ≥ 1.5 × the 50-day average.
- **Stop:** just below the box bottom.
- **Exit:** trail the stop to each new box bottom; exit when it is hit.
- **Evidence:** Darvas's 1960 book only. It is a 52-week-high breakout variant.

### S3. Turtle / Donchian 20/55

**Grade:** MODERATE for diversified futures (Hurst, Ooi and Pedersen 2017; MOP 2012), WEAK for single stocks. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **System 1:** buy-stop at the previous 20-day high; exit on a 10-day-low stop.
- **System 2:** buy-stop at the previous 55-day high; exit on a 20-day-low stop.
- **Initial stop:** entry − 2N, where N = ATR(20).
- **Unit size:** 1% of equity / N. Add a unit at each +0.5N, up to 4 units. Total portfolio risk ≤ 12%.
- **Skip** the original "skip after a winner" filter, which was designed for futures.
- **Evidence:** trend following works across asset classes. On single stocks, the trading-range-break results in STW (1999) do not hold out-of-sample.
- **Failure modes:** win rate around 30–40%; long flat stretches; whipsaw costs.

### S4. O'Neil 52-week-high breakout on volume

**Grade:** MODERATE for the 52-week-high effect, WEAK for the rule. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL. Our earlier `near_high` rank strategy failed and is disabled; publish that result next to this one.

- **Setup:**
  - C > SMA50 > SMA200 and RS rating ≥ 80.
  - The stock has not exceeded its prior high for at least 25 days (a base of 5 weeks or more), and the base is no deeper than 33%.
- **Entry:** close ≥ previous 52-week high with volume ≥ 2 × the 50-day average. Fill at the next open, and skip it if the open is more than 5% above the pivot (too extended).
- **Stop:** −7%.
- **Exit:** +20–25% profit-take (O'Neil's rule; optionally keep holding if the move took under 3 weeks), close < SMA50 on above-average volume, or a 40-day time stop.
- **Evidence:**
  - George and Hwang (2004, JF), who show nearness to the 52-week high explains much of momentum with no long-run reversal ([summary](https://academicnewsletter.sufe.edu.cn/info/361244)).
  - Contrary results for emerging-market *indices* ([Griffith](https://research-repository.griffith.edu.au/items/41995ba4-ea62-565b-bc6a-9233b7978ae0)).
  - The high-volume return premium (Gervais, Kaniel and Mingelgrin 2001, from memory).

### S5. Pullback to 20/50 EMA in RS leaders

**Grade:** WEAK. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Universe:** RS rating ≥ 80, C > SMA200 and SMA50 > SMA200.
- **Setup:** the low comes within 0.5 × ATR14 of EMA20 (variant: EMA50) after at least 3 down closes in the last 5 days, and the close stays above SMA50.
- **Trigger:** the next day's high exceeds the setup day's high. Use a buy-stop at setup high + 0.1%.
- **Stop:** pullback low − 0.25 × ATR, risking at most 8%.
- **Exit:** close < EMA20 after +1R, a 2.5R target, or a 15-day time stop.
- **Evidence:** combines momentum (STRONG) with short-term reversal (Jegadeesh 1990), whose gross profits mostly vanish after costs (Avramov, Chordia and Goyal 2006, from memory). Our `rsi2_pullback` failed. Indian delivery costs of 0.25–0.4% per round trip are the main obstacle.

### S6. Post-earnings drift / earnings-gap continuation

**Grade:** MODERATE. **Data:** D+E. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL, and promote it if it holds on the 2024–26 holdout.

- **Events:** results dates come from the archived PR-zip `bm` files ("Financial Results" purpose), cross-checked against `an` announcements. Day 0 is the meeting date. Because release times vary, the reaction window is days 0 to +1.
- **Signal:**
  - EAR = Σ over days 0..+1 of (r_stock − r_Nifty).
  - Go long if EAR ≥ +5%, or if EAR is in the top 20% of all events seen so far that season (percentile computed only from past events).
  - Also require volume on day 0 or +1 ≥ 2 × the 50-day average, and the close on +1 in the upper half of that day's range (the gap held).
- **Entry:** close of day +1, or the open of +2.
- **Exit:** after 40 trading days (before the next results), on a stop at the day-0 low (gap filled), or at −10%.
- **Size:** equal weight, at most 10 positions.
- **Bad-news drift:** because shorting overnight is impossible, use it only as an "exit or avoid" flag on existing holdings.
- **Evidence:**
  - Bernard and Thomas (1989) and Brandt et al. (2008) on drift after earnings-announcement returns (from memory).
  - India is mixed: the [IIMB study](https://repository.iimb.ac.in/handle/2074/20501) finds drift into the third month; [Nottingham](https://eprints.nottingham.ac.uk/26569) finds drift for more than a week after bad news only; [Gupta and Dhusia 2021](https://journals.vutbr.cz/index.php/trends/article/view/541) find none.
  - US PEAD has largely disappeared for large caps since the 2000s (Martineau 2022, from memory).
- **Failure modes:** errors in the event-timing proxy; drift weaker in large caps; overlapping results seasons crowd capacity.

### S7. Sector rotation

**Grade:** MODERATE. **Data:** X. **Verdict:** IMPLEMENT.

- **Universe:** a non-overlapping set of about 12 NSE sector indices: Bank, IT, Pharma, FMCG, Auto, Metal, Energy, Realty, Media, Infrastructure, Commodities and India Consumption. Do not mix Bank with Private Bank or Financial Services.
- **Monthly rule:**
  - Score = 6-month return, with 12-1 as a variant.
  - Hold the top 3 sectors, each only if its index is above its own 200-DMA; otherwise that third of capital goes to cash.
- **Vehicles:**
  - (a) Sector ETFs (BANKBEES, ITBEES, PHARMABEES, AUTOBEES and others). Check liquidity and the start date of each history.
  - (b) The top 3 momentum stocks inside each chosen sector. This needs the `industry` column from the universe CSV, mapped point-in-time.
- **Evidence:** Moskowitz and Grinblatt (1999, JF; [RePEc](https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html)). Disputed by Grundy and Martin (2001); reframed as factor momentum by Arnott et al. (2018). No strong India-specific paper was found.
- **Failure modes:** sectors with few, concentrated constituents; gaps between index and ETF returns; reversals in months when sector leadership flips.

### S8. Bollinger squeeze

**Grade:** FOLKLORE. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Indicator:** BB(20, 2). Bandwidth = (upper − lower) / middle.
- **Squeeze:** bandwidth ≤ its 5th percentile over the last 252 days.
- **Entry:** the first close above the upper band within 10 days of a squeeze, with C > SMA200.
- **Stop:** 1.5 × ATR.
- **Exit:** close < SMA20.
- **Note:** volatility does mean-revert, but nothing predicts the *direction* of the breakout.

### S9. NR7 / inside day

**Grade:** FOLKLORE (Crabel 1990; Connors and Raschke 1995). **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Setup:** NR7 = today's range is the smallest of the last 7 days. ID = an inside day. NR7-ID = both.
- **Filter:** C > SMA50.
- **Entry:** next day, buy-stop at the setup high.
- **Stop:** the setup low.
- **Exit:** after 3 days or a 2R target.
- **Intraday version:** the same levels, but exit at 15:00. It needs I-data to resolve days when both levels are hit.

### S10. Connors RSI(2) / cumulative RSI

**Grade:** WEAK. **Verdict:** SKIP-NO-EVIDENCE; already tested and disabled. List it on a "tested and rejected" page with its numbers.

- **RSI(2) rule:** C > SMA200 and RSI2 < 5 → buy at the close; exit when C > SMA5. Connors used no stop.
- **Cumulative RSI rule:** RSI2(t) + RSI2(t−1) < 35 → buy; exit when RSI2 > 65.
- **Evidence:** Connors and Alvarez (2009), largely in-sample. A community test finds it mostly unprofitable ([ProRealCode](https://prorealcode.com/prorealtime-trading-strategies/rsi-2p-larry-connors)). The average gain per trade is smaller than Indian delivery costs (STT 0.1% on each side).

### S11. Golden cross on single stocks

**Grade:** WEAK. **Verdict:** SKIP-NO-EVIDENCE. The index version is kept as a variant of L3.

It lags badly. Brock, Lakonishok and LeBaron's in-sample MA results do not survive Sullivan, Timmermann and White's out-of-sample test.

### S12. 52-week-low mean reversion

**Grade:** evidence against. **Verdict:** SKIP-NO-EVIDENCE. It can be run once as a **negative control** on the survivorship-free universe.

- **Typical rule:** buy within 5% of the 52-week low, exit at +10% or after 20 days.
- **Why most versions fail:**
  1. It buys losers, which keep losing (momentum); stocks far from their 52-week high underperform (George and Hwang).
  2. Long-term reversal (De Bondt and Thaler 1985) needs 3–5-year losers and sits mostly in small, distressed stocks around January.
  3. **Survivorship bias makes it look good:** stocks that went to zero or were delisted are missing from a current-constituents dataset.
  4. Delivery costs.
- India shows some long-run overreaction (NSE RP), but nothing at a swing horizon.

---

## 6. Rule cards: intraday (MIS, cash equity)

Shared defaults for intraday cards:
- **Universe:** F&O stocks (about 200; they have dynamic price bands and are not trade-to-trade), price ≥ ₹100, 20-day average turnover ≥ ₹100 crore. Add NIFTYBEES.
- **Exclude:** BE, BZ and other trade-to-trade series (intraday not allowed); ex-dates; Muhurat sessions.
- **"In play" filter, used where stated:** first-5-min volume ≥ 2 × its 14-day average for that slot (Zarattini, Barbon and Aziz), or |gap| ≥ 1.5%, or a results or announcement day.
- **Signals and fills:** signals on bar close fill at the next bar's open + slippage. Stop entries fill at max(open, level) for longs.
- **Same-bar ambiguity:** check 1-min bars; if still ambiguous, assume the stop was hit first.
- **Forced flat:** 15:00 for F&O stocks, 15:15 for non-F&O stocks and ETFs.
- **Sizing:** risk 0.5% of equity per trade. Notional ≤ 4 × equity (SEBI peak-margin rules cap MIS at about 5×). Participation ≤ 1% of that bar's volume.
- **Costs and tax:** the intraday cost model in §3a and speculative tax.

### I1. Opening Range Breakout family (5/15/30/60-min, first-hour high/low, opening drive)

**Grade:** WEAK to MODERATE. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Opening range:** the high and low of 09:15 to 09:15+N, with N ∈ {5, 15, 30, 60}. N = 60 is the "first-hour high/low breakout".
- **A. Classic ORB:** after the range closes, place an OCO buy-stop at OR high + 0.05% and sell-stop at OR low − 0.05%. Stop at the opposite side of the range (or at the mid-point if the range > 1.5 × ATR14/4). Target 2R, or hold to the forced-flat time. One trade per stock per day.
- **B. Zarattini-Barbon-Aziz (2024) version, N = 5:** trade in the direction of the first 5-min candle (long if close > open). Stop-entry at the 5-min high (low for shorts). Stop = 10% of the 14-day daily ATR from entry. Hold to end of day. Only the top 20 in-play stocks.
- **C. Opening drive:** the first 15-min bar's range ≥ 1.5 × its 20-day average and it closes in the top or bottom 20% of its range with volume ≥ 2×. Enter at the next bar's open in that direction. Stop at the drive bar's midpoint. Trail under 5-min swing lows.
- **Evidence:**
  - Zarattini and Aziz (2023), ORB on QQQ ([SSRN 4416622](https://papers.ssrn.com/abstract=4416622)).
  - Zarattini, Barbon and Aziz (2024), 7,000+ US stocks, in-play filter is key ([SSRN 4729284](https://ssrn.com/abstract=4729284)). The authors run trading businesses.
  - Holmberg et al. (2013, FRL) on oil futures ([RePEc](https://ideas.repec.org/a/eee/finlet/v10y2013i1p27-33.html)).
  - An independent replication on index CFDs found the gross results reproduced but **net returns were about zero** after spread and slippage ([MQL5](https://www.mql5.com/en/blogs/post/776235)).
  - No peer-reviewed Indian study was found.
- **India-specific note:** NSE changes the pre-open auction from 7 Sep 2026 (CAS phase 2), so opening-range statistics before and after that date may differ. Split the sample.

### I2. VWAP trend

**Grade:** WEAK. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Instrument:** NIFTYBEES (closest to QQQ), plus the top 30 F&O stocks by liquidity.
- **Rule:** from 09:20, on each 5-min close (1-min as a variant), be long if close > session VWAP × 1.001 and short if close < VWAP × 0.999 (a hysteresis band). Hold for at least 2 bars. Flat at the forced-flat time.
- **Evidence:** Zarattini and Aziz (2023), QQQ 2018–2023, author-reported Sharpe of about 2.1 ([SSRN 4631351](https://ssrn.com/abstract=4631351)). One working paper, one instrument, authors with commercial interests.
- **Failure modes:** flips on choppy days; each flip costs about 0.1–0.2% all-in in India.

### I3. VWAP pullback and VWAP reversion

**Grade:** FOLKLORE / WEAK. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Pullback (trend days):**
  - After 10:15, the stock's 09:15–10:15 return is ≥ +1% and it has closed above VWAP on at least 80% of bars.
  - A bar's low touches VWAP and the bar closes above it: buy at the next open.
  - Stop: the pullback bar's low − 0.1%. Target: the day's high, or 2R.
  - Mirror the rules for shorts.
- **Reversion (range days):**
  - Use volume-weighted VWAP σ-bands.
  - When close > VWAP + 2σ and 5-min RSI(14) > 75, short and target VWAP; stop at +3σ. Mirror for longs.
  - Skip days that already qualify as trend days (opening range broken with 2× volume).
- **Evidence:** VWAP is an execution benchmark, not a proven signal. Earning money by providing liquidity (fading moves) needs maker-side costs, which retail does not get.

### I4. Gap-and-go vs gap fade

**Grade:** WEAK (go), WEAK to MODERATE (fade of non-news gaps). **Data:** I+E. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Gap:** open / official previous close − 1.
- **Gap-and-go:**
  - Gap ≥ +2% *with* news (results or an announcement in `bm`/`an`) and first-5-min volume ≥ 3×.
  - Buy-stop at the 15-min OR high after 09:30, with price above the open.
  - Stop: OR low. Hold to the forced-flat time.
- **Gap fade:**
  - Gap ≥ +2% with *no* news, and the 09:15–09:30 bar makes no new high and closes below the open.
  - Sell-stop below the 15-min low. Target: the previous close (gap filled). Stop: the 15-min high.
  - Mirror for gap-downs (buy the fade).
- **Evidence:**
  - Berkman, Koch, Tuttle and Zhang (2012, JFQA): high-attention stocks have positive overnight returns that reverse during the day (from memory).
  - Lou, Polk and Skouras (2019, JFE): momentum is earned overnight, while reversal-type profits come intraday, often with opposite signs ([paper](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)).

### I5. Intraday momentum (Gao, Han, Li, Zhou 2018)

**Grade:** MODERATE globally; no India evidence. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Signal:** r1 = price at 09:45 / official previous close − 1. As in the paper, this includes the overnight move. Optional: also use the return of the second-to-last half hour.
- **Trade:** enter in the direction of sign(r1), only if |r1| > 0.5 × its 60-day standard deviation (the paper finds a stronger effect on volatile, high-volume and news days).
  - **NIFTYBEES** (not F&O, continuous trading to 15:30, MIS cutoff 15:20): enter at 14:45, exit at 15:15.
  - **F&O stocks:** enter at 14:30, exit at 15:00, before the 15:05 square-off.
- **Evidence:**
  - Gao, Han, Li and Zhou (2018, JFE 129(2):394–414): S&P 500 ETF 1993–2013 and 10 other ETFs, with an R² of only about 2% ([WUSTL](https://profiles.wustl.edu/en/publications/market-intraday-momentum/)).
  - Baltussen, Da, Lammers and Martens (2021, JFE) tie the effect to option dealers' gamma hedging (from memory). That makes it plausible in India's very large options market, but the sign depends on how dealers are positioned.
  - Indonesian evidence supports it ([UMS](https://eprints.ums.edu.my/id/eprint/42874)).
  - The [IIMA intraday paper](https://www.iima.ac.in/hindi/index.php/node/16399) covers volatility patterns only.
- **Main risk:** the expected half-hour return is a few basis points, while the round trip costs 5–8 basis points plus spread. Net returns may well be negative; the test must show it.
- **CAS caveat:** the last half hour in the paper ends at the close. Under MIS in F&O stocks we cannot reach the post-15:05 window or the closing auction.

### I6. CPR / Camarilla / floor pivots

**Grade:** FOLKLORE. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL, using textbook formulas only so the test is not data-mined.

- **Floor pivots:** P = (H+L+C)/3 of the previous day; R1 = 2P − L; S1 = 2P − H; R2 = P + (H−L); S2 = P − (H−L).
- **CPR:** BC = (H+L)/2 and TC = 2P − BC; width = |TC − BC| / P.
- **Narrow-CPR breakout:** width in the bottom 20% of the last 20 days, the open is above TC, and the first 15-min close is above TC. Go long; stop below BC; targets R1 then R2; flat at the forced-flat time. Mirror for shorts.
- **Camarilla:** R3/S3 = C ± 1.1·(H−L)/4 and R4/S4 = C ± 1.1·(H−L)/2. Fade at R3/S3 on a reversal bar (stop at R4/S4, target P); trade breakouts beyond R4/S4 (stop at R3/S3).
- **Evidence:** none peer-reviewed. Support and resistance clustering in FX (Osler 2000, from memory) is the closest result.

### I7. Supertrend

**Grade:** FOLKLORE. **Verdict:** IMPLEMENT-AS-EXPERIMENTAL.

- **Indicator:** ATR(10) with multiplier 3 (popular Indian alternative: 7, 3), on 5-min or 15-min bars for intraday and daily bars for swing.
- **Rule:** long when the close crosses above the line, short when it crosses below, flat at the forced-flat time. The swing version is long-only and exits on a flip.
- **Note:** it is an ATR trailing stop, so it is trend-following with a lot of whipsaw.

### I8. Closing-hour trend

**Grade:** MODERATE (index), WEAK (stocks). **Verdict:** IMPLEMENT-AS-EXPERIMENTAL, as part of the I5 family.

- **Rule:** at 14:05 (F&O stocks) or 14:15 (NIFTYBEES and non-F&O), if the day's return vs the previous close is ≥ +1%, close > VWAP and price is within 0.3% of the day's high → buy. Exit at 15:00 or 15:15. Mirror for shorts.
- **Limitation:** the CAS and MIS rules mean the real final 15 minutes and the closing auction cannot be traded under MIS in F&O stocks.

---

## 7. Intraday backtest pitfalls (all must be handled in the intraday engine)

1. **Bar granularity.** On 5-min OHLC the order of events inside a bar is unknown. Use 1-min bars, and when still ambiguous assume the stop was hit first. Never fill at the high or low of the bar that triggered the signal.
2. **Next-bar fills.** A signal on bar t's close is filled at the open of t+1 plus slippage. Stop orders fill at max(open, level); a gap through the level fills at the open.
3. **Slippage and spread.** Use a per-stock model: half the median spread plus an impact term k·√(qty / bar volume). Cap participation at 1% of the bar's volume. Add extra slippage for stop entries and exits.
4. **Opening and closing mechanics.**
   - The 09:00–09:08 pre-open auction sets the open, and the first bar is the noisiest. The pre-open rules change from 7 Sep 2026.
   - Before CAS (3 Aug 2026), the official close was the VWAP of 15:00–15:30, so the **official close ≠ the last 5-min bar's close**. Since CAS, the official close is the auction price for F&O stocks. This also affects the *daily* engine's fill-at-close assumption.
   - Split every intraday sample at 3 Aug and 7 Sep 2026.
5. **Broker cutoffs.** MIS square-off is 15:05 for F&O stocks and 15:20 for non-F&O stocks ([FYERS](https://support.fyers.in/portal/en/kb/articles/what-is-the-intraday-square-off-timings-at-fyers)). Being auto-squared costs ₹59 per order. FYERS can bring cutoffs forward on volatile days.
6. **Price bands.** Non-F&O stocks have fixed 2/5/10/20% circuits, and a stock locked at its limit cannot be exited. Trade-to-trade series cannot be traded intraday. Restrict intraday to F&O stocks and liquid ETFs.
7. **Survivorship and universe drift.** The F&O list changes over time. Use the list as of each date; the survivorship-free session can supply it.
8. **Data quality.**
   - Check FYERS epoch timestamps convert correctly to IST.
   - Compare against the official bhavcopy every day: the sum of 1-min volume ≈ daily volume, the first open = official open, and the high and low match.
   - Check for missing minutes in illiquid names, stray bad ticks, and whether intraday history is adjusted for splits around ex-dates.
9. **Statistical power.** About 250 days is too few to separate a Sharpe of 1 from 0 for a single instrument. Pool across stocks, report the 95% confidence interval, and keep the archiving job running.
10. **Multiple testing.** ORB windows, pivot types and thresholds add up to many variants. Fix the parameters from the literature *before* testing. Report the number of variants tried and a deflated Sharpe (Bailey and López de Prado 2014, from memory) or White's Reality Check / Hansen SPA ([STW 1999](https://www.fmg.ac.uk/sites/default/files/2020-11/dp303.pdf)).
11. **Regime events.** Flag weekly index-option expiry days, results days, Budget day and RBI policy days; report results by day type.
12. **Live constraints.** The FYERS WebSocket handles at most 100 symbols, so live scanners must pre-select (for example the top 100 in play after 09:20). The daily login token means the scheduler must handle a missing token cleanly.
13. **Tax.** Report intraday results after tax at the speculative-income slab rate, not STCG.

---

## 8. Suggested implementation order and honesty rules for the platform

- **Phase A (daily data, strongest evidence):**
  - L1 and L2 with the NSE-index replication check, L10, L3, L4, L5 (after the constituents land) and S7.
  - An "NSE factor index gallery" of L6, L7 and L8 proxies from the daily index file. It costs almost nothing to add and is very informative.
  - Add a cash series (Nifty 1D Rate), ETF symbols and a dividend total-return adjustment.
- **Phase B (daily data, experimental swing):**
  - Build the `bm` results-date archive, then S6.
  - Then S1, S4, S3, S2, S8, S9 and S5.
  - The engine needs stop-order entries and same-bar ambiguity rules.
- **Phase C (intraday):**
  - A FYERS 1-min fetcher with rate limiting (fetch 1 year now, then archive daily).
  - A new intraday engine with MIS cutoffs and the §3a cost and tax model.
  - Then the I1 family, I5/I8, I4, I2/I3, and finally I6/I7.
- **Show "tested and rejected" in the UI:** S10, S11 (stocks), S12, `near_high`, `rsi2_pullback` and `legacy_rules`, each with its result.
- **Every strategy page shows:** results net of costs and after tax; a walk-forward with a fixed holdout (for example, design on 2018–2022 and hold out 2023–2026); the number of variants tried; the timing-luck range; trade count with confidence intervals; and the benchmarks (Nifty 50, Nifty 500 equal weight, and the matching NSE factor index).
- **Verdict labels:** Works / Mixed / Fails / Not enough data.

---

## 9. Sources

**Fetched this session**

*Regulators and exchanges*
- [SEBI intraday study PDF, Jul 2024](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf)
- [SEBI F&O press release, Sep 2024](https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html)
- [NSE CAS page](https://www.nseindia.com/static/products-services/closing-auction-session)
- [NSE CAS circular](https://nsearchives.nseindia.com/content/circulars/CMTR75479.pdf)
- [Nifty200 Momentum 30 whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf)
- [Nifty200 Momentum 30 factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf)
- [Nifty100 Low Volatility 30 methodology](https://archives.nseindia.com/content/indices/Method_Nifty100_Low_Volatility_30.pdf)
- [NSE research paper on momentum (res_paperfinal223)](https://nsearchives.nseindia.com/content/research/res_paperfinal223.pdf)
- [NSE RP 2, Feb 2012](https://nsearchives.nseindia.com/research/content/RP_2_Feb2012.pdf)

*Broker (FYERS) and charges*
- [FYERS charges list](https://fyers.in/charges-list.md)
- [FYERS pricing](https://fyers.in/pricing.md)
- [FYERS intraday square-off timings](https://support.fyers.in/portal/en/kb/articles/what-is-the-intraday-square-off-timings-at-fyers)
- [FYERS API plans & limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)
- [FYERS forum: 100-day history limit](https://fyers.in/community/fyers-api-rha0riqv/post/limit-in-history-SyjytuRSpdWwNBd)
- [Zerodha on NSE transaction charges](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/why-am-i-being-charged-higher-transaction-charges)

*Indian academic and index research*
- [IIMA Indian Fama-French / momentum factor library](https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/)
- [Joshipura, IMFI 2020](https://www.businessperspectives.org/images/pdf/applications/publishing/templates/article/assets/13547/IMFI_2020_02_Joshipura.pdf)
- [Joshipura, Applied Finance Letters](https://ojs.aut.ac.nz/applied-finance-letters/article/download/32/31)
- [IIMB PEAD study](https://repository.iimb.ac.in/handle/2074/20501)
- [Nottingham earnings event study](https://eprints.nottingham.ac.uk/26569)
- [Gupta and Dhusia 2021](https://journals.vutbr.cz/index.php/trends/article/view/541)
- [India value premium, IJAF 2012](https://ideas.repec.org/a/icf/icfjaf/v18y2012i2p48-62.html)
- [India value premium, Inderscience](https://www.inderscience.com/filter.php?aid=120448)
- [NMIMS Management Review, Apr 2018 issue](https://management-review.nmims.edu/docs/2018/April/Issue-1(4).pdf)
- [Christ University: industry value premium declining](https://archives.christuniversity.in/items/show/15286)
- [IIMA intraday patterns paper](https://www.iima.ac.in/hindi/index.php/node/16399)
- [Indonesian intraday winners vs losers](https://eprints.ums.edu.my/id/eprint/42874)

*International papers and summaries*
- [Gao, Han, Li, Zhou (2018) record](https://profiles.wustl.edu/en/publications/market-intraday-momentum/)
- [Lou, Polk, Skouras: A Tug of War](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)
- [Zarattini and Aziz, SSRN 4416622 (ORB)](https://papers.ssrn.com/abstract=4416622)
- [Zarattini, Barbon, Aziz, SSRN 4729284 (stocks in play)](https://ssrn.com/abstract=4729284)
- [Zarattini and Aziz, SSRN 4631351 (VWAP)](https://ssrn.com/abstract=4631351)
- [MQL5 ORB replication (net about zero)](https://www.mql5.com/en/blogs/post/776235)
- [Holmberg et al. 2013, FRL](https://ideas.repec.org/a/eee/finlet/v10y2013i1p27-33.html)
- [Sullivan, Timmermann, White 1999 (FMG DP303)](https://www.fmg.ac.uk/sites/default/files/2020-11/dp303.pdf)
- [Brock, Lakonishok, LeBaron 1992](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html)
- [Moskowitz and Grinblatt 1999](https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html)
- [George and Hwang 2004 summary](https://academicnewsletter.sufe.edu.cn/info/361244)
- [52-week high on emerging-market indices (Griffith)](https://research-repository.griffith.edu.au/items/41995ba4-ea62-565b-bc6a-9233b7978ae0)
- [Quantpedia: asset-class trend following](https://quantpedia.com/strategies/asset-class-trend-following)
- [Antonacci summary](https://algoadvantage.substack.com/p/gary-antonacci-absolute-and-relative)

*Practitioner, product and community*
- [Ambit Coffee Can factsheet, Aug 2026](https://www.ambit.co/wp-content/uploads/2026/08/Ambit-Coffee-Can-Portfolio-Factsheet_Aug_26.pdf)
- [LIQUIDBEES mechanics (tradingqna)](https://tradingqna.com/t/why-liquidbees-value-doesnt-vary-from-1000-in-spite-of-having-good-volumes-on-this-etf/19)
- [LIQUIDBEES factsheet (PersonalFN)](https://www.personalfn.com/factsheet/nippon-india-etf-liquid-bees)
- [ProRealCode RSI(2) test](https://prorealcode.com/prorealtime-trading-strategies/rsi-2p-larry-connors)
- [Freefincal momentum index explainer](https://freefincal.com/nifty200-momentum-30-index-a-new-strategy-index-from-the-nse/)
- [Business Standard on the SEBI intraday study](https://www.business-standard.com/markets/news/over-70-intra-day-traders-incur-losses-during-fy23-reveals-sebi-study-124072401110_1.html)

**Cited from memory, not re-fetched; verify before quoting**
- Faber SSRN 962461 and Antonacci SSRN 2042750 (the SSRN IDs).
- Jegadeesh and Titman 1993; Jegadeesh 1990; De Bondt and Thaler 1985.
- Daniel and Moskowitz 2016; Frazzini and Pedersen 2014; Baker, Bradley and Wurgler 2011; Ang et al. 2006.
- Novy-Marx 2013; Asness, Frazzini and Pedersen (QMJ).
- Bernard and Thomas 1989; Brandt et al. 2008; Martineau 2022.
- Moskowitz, Ooi and Pedersen 2012; Hurst, Ooi and Pedersen 2017.
- DeMiguel, Garlappi and Uppal 2009; Plyakha, Uppal and Vilkov 2012.
- Berkman et al. 2012; Baltussen et al. 2021; Gervais, Kaniel and Mingelgrin 2001; Avramov, Chordia and Goyal 2006.
- Barber, Lee, Liu and Odean (Taiwan); Chague, De-Losso and Giovannetti 2019; Bailey and López de Prado 2014; Osler 2000.
- Books: Connors and Alvarez 2009, Crabel 1990, Darvas 1960, Bollinger 2001, O'Neil, Minervini 2013.

**Unverified tax and cost points:** STT on ETF units, and the gold-ETF capital-gains rules. Check both against a real FYERS contract note or with a CA.