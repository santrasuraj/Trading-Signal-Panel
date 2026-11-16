# Trade Ideas (trade-ideas.com): stock scanning and AI trading platform, profile as of November 2026

Research date: 2026-11-11. Sources are labelled as **[Official]** (Trade Ideas' own pages, marketing or help docs), **[Independent]** (third-party review with no obvious commercial tie), **[Affiliate/Competitor]** (earns referral fees or sells a rival product), or **[User]** (forum/review-site posts). Unless a finding says "independently verified", treat every performance number as a vendor claim.

## 1. Real-time scanning: alerts, filters, scan building, refresh speed, channels, top lists, alert windows

### Takeaway
Scanning runs on Trade Ideas' servers. It offers 310 streaming alert types and 249 screener filters ("500+ alerts and filters"). Alerts fire on every qualifying trade (tick-driven), but Top Lists (screeners) refresh only every 15 seconds. You build scans by combining alerts and filters in configuration windows, through a formula editor, or, since about July 2026, with a natural-language AI Assistant. The pre-built "Channel Bar" adds 20+ ready-made layouts.

### Cited Findings
- **[Official]** The homepage lists 310 stock alerts, 249 screener filters and 56 scanner pages. It says alerts fire on each trade, not on candle close, and Top Lists refresh every 15 seconds. — [Trade Ideas homepage](https://trade-ideas.com/)
- **[Official]** The speed page (by CEO Daniel Mirkin, updated October 2026, prices checked 11 Oct 2026) repeats the figures. It says "Streaming Alerts fire on every qualifying trade, and Top Lists update every 15 seconds." It also repeats 310 Streaming Alerts, 249 Screener Filters and 56 scanner pages. — [How fast is Trade Ideas](https://www.trade-ideas.com/how-fast-is-trade-ideas/)
- **[Official]** The 2026 pricing page lists these TI Standard features: full scans ("Alert Windows"), screeners ("Top List Windows"), Multi-Strategy windows, "500+ alerts and filters", AI Scan Building Assistant, Formula Editor, 20+ Channel Bar templates, 60-trading-day historical scanning, customizable Stock Races, Compare Count windows, unlimited watchlists and price alerts. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** The Windows app (TI Pro) is organised into window types: Alert Window (alert configuration, strategies, filters, history, alert logging), Top List Window (including a Real-Time Stock Race and a Treemap view), Multi-Strategy Window, Single Stock Window, Compare Count Window, Chart Window, Price Alerts Window, Premium AI Strategy windows, Premium RBI/GBI windows, plus free-floating or docked layouts and a Channel Bar with custom channels. — [TI user guide, Features Overview (ch. 32)](https://trade-ideas.com/guide/chapter/32/32Features_Overview.html)
- **[Official]** The browser "Market Dashboards" are MarketScope360, SectorScope360, Stock Deep Dive, Stock Momentum, Top Lists, PositionScope and Portfolio Master Challenge. Other tools are Market Explorer and "Stocks Like This". — [TI user guide, Features Overview](https://trade-ideas.com/guide/chapter/32/32Features_Overview.html)
- **[Official]** Premium adds RBI/GBI windows ("Red Bar Ignored / Green Bar Ignored" pattern windows) on 5-, 15- and 30-minute bars. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** The AI Assistant builds live Alert and Top List (screener) windows from plain-English typed or spoken requests and can read the chart you have open. Trade Ideas says it is included in TI Pro on every plan. — [Trade Ideas AI Trading Assistant page](https://www.trade-ideas.com/ai-trading-assistant/)
- **[Affiliate]** A third-party guide dates the AI Assistant's release to July 2026. A recorded test reportedly opened a live whole-market Top List in under 6 seconds from a voice or typed prompt. — [DayTradingToolkit, AI Assistant](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-ai-assistant), per search summary; not independently checked.
- **[Independent]** StockBrokers.com (15 June 2026) highlights pre-defined screeners and watchlists ("Channels"), heatmaps, the Stock Race visualization, Market Pulse, replay and the Scope 360 dashboard. It does not give the number of alerts or filters. — [StockBrokers.com review](https://www.stockbrokers.com/review/tools/trade-ideas)
- **[Official]** The learning-center material says Trade Ideas scans "8,000+" US stocks in real time. — [Trade Ideas, real-time stock scanning](https://www.trade-ideas.com/learning-center/stock-scanning/real-time-stock-scanning/)

### Inferences
- The two update models differ sharply. Alert windows are event-driven at the tick level. Top Lists are periodic snapshots at 15 seconds. A competitor can match the first and clearly beat the second (for example, a 1-second or event-driven screener refresh).
- "500+ alerts and filters" equals the homepage's 310 + 249 = 559. The figures are consistent.
- Pre-built channels plus the AI Assistant are what Trade Ideas offers against its known learning-curve problem. Natural-language scan building and good default layouts are therefore table stakes for a gap analysis.

### Gaps
- No official limit on the number of simultaneous alert windows or symbols per window was found.
- I found no exact count of Channel Bar channels or layouts beyond "20+ templates".
- No independent test of the AI Assistant's accuracy was found.

## 2. Holly AI: how it works, variants (Holly Grail / Holly 2.0 / Holly Neo), and how signals are presented

### Takeaway
Holly is an intraday-only strategy-selection engine. Each night it backtests and re-optimises a fixed library of proprietary, non-customisable strategies; the current guide says "over 60", while older and third-party figures range from about 50 to 70. It then deploys only the statistically best strategies the next session. Each signal is a clear directional call (symbol, long/short, entry, stop, usually a target and expected hold time), and the user switches between three "Segments": Holly Grail, Holly 2.0 and Holly Neo. A newer charting signal, TI Wave, shows simple B/S markers on any chart.

### Cited Findings
- **[Official]** The Holly guide says Holly backtests "over 60 strategies" every night and optimises each by removing under-performing parameters (for example, a price range) and retesting. She keeps only the strategies with the "highest statistical chance to deliver profitable trades" for the next day. There are usually 5 to 25 trades per day. — [Holly AI guide (print version)](https://www.trade-ideas.com/hollyguide/print.html)
- **[Official]** The strategy list says: "The over 60 strategies our AI employs are described below" and "The parameters are proprietary and cannot be customized". For target, hold time and stop type, it says to "Consult the main AI window". — [Holly AI Strategies](https://www.trade-ideas.com/hollyguide/Holly_AI_Strategies.html)
- **[Official]** Some strategies are time-gated. Sunrise Mover is active shortly after the open and stops 45 minutes after the bell. Power Hour Long and Short trigger only in the final hour. Pushing Through Resistance waits about 40 minutes after the open. Neo's Breakout and Pullback strategies focus on high-volume stocks "in the news". — [Holly AI Strategies](https://www.trade-ideas.com/hollyguide/Holly_AI_Strategies.html)
- **[Official]** Holly has three Segments, each with its own assigned strategies, and you switch between them from a Segments menu. Holly is intraday only and does not hold overnight. Re-entry rule: if a stop is hit and price comes back to the midpoint between stop and entry, Holly re-enters, keeping the original stop, and treats it as a new trade. — [Holly AI guide](https://www.trade-ideas.com/hollyguide/print.html)
- **[Official]** P&L in the AI windows uses the "AI Risk Size", which defaults to 100 shares per trade. It can be set to Dollars, Shares, Risk or Default. Example: risking $100 with a $0.20 stop gives 500 shares. — [Holly AI guide](https://www.trade-ideas.com/hollyguide/print.html)
- **[Official]** The current homepage describes Holly AI signals as buy signals on large movers. Each has an entry and a stop, plus a re-entry point if the stock stops out and turns back. The stop is "usually about 3%" from entry, and the page warns that gaps can enlarge losses. — [Trade Ideas homepage](https://trade-ideas.com/)
- **[Official]** The signals page says each Holly signal gives a symbol, entry price and suggested stop. Holly closes her own tracked trades by end of day, and the user decides whether to hold. TI Wave signals show as "B" and "S" markers on any stock and timeframe, with AI-adjusted moving-average bands. Disclaimer: "Many signals won't work out. Past results, including backtests, don't guarantee future results." — [Trade Ideas, trading signals](https://www.trade-ideas.com/features/trading-signals/)
- **[Official]** The 2026 pricing page says "Holly AI buy and sell signals, each with an entry and stop", plus "Smart Risk Levels (AI-generated stops and targets on every chart)". All of this is TI Premium only. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** Learning-center pages describe Holly as "an AI strategist that ranks opportunities rather than a ChatGPT-style conversational chatbot". They warn that "search can overfit if validation is weak" and that strategies can fail when market regimes change. They give no strategy count, thresholds or performance figures. — [What is Holly AI](https://www.trade-ideas.com/learning-center/ai-in-trading/what-is-holly-ai/); [How Holly AI generates trade signals](https://www.trade-ideas.com/learning-center/ai-in-trading/how-holly-ai-generates-trade-signals/)
- **[Affiliate]** According to DayTradingToolkit (published 25 Feb 2026, updated 7 Nov 2026):
  - Holly (Holly Grail) is the balanced original. Holly 2.0 is the same engine with more risk and wider targets. Holly Neo leans on real-time chart patterns forming intraday.
  - Each signal shows ticker, strategy, direction, entry, stop, target and expected hold time (for example, about 45 minutes), with an arrow on the chart.
  - Holly re-simulates on "the last few months" of data each night.

  — [DayTradingToolkit, Holly explained](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-holly-ai-explained)
- **[Third-party, undated, likely about 2016–2017]** An Equities.com article (reprinted Trade Ideas content) says Holly ran an overnight "Quantitative Combine" of "over a million simulated trades against 55 different concepts". Only strategies with a success rate above 60% and a 2:1 profit factor were visible the next day. — [Equities.com](https://www.equities.com/news/holly-float-on-leads-7-other-trade-ideas-3), via search snippet; not fetched in full.
- **Strategy-count conflict:** StockBrokers.com (June 2026) says "nearly 50 predefined strategies" ([StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)). TradeAlgo (March 2026) says "~70 strategies run nightly" ([TradeAlgo](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)). The official guide says "over 60" ([Holly guide](https://www.trade-ideas.com/hollyguide/Holly_AI_Strategies.html)). Equities.com said 55 concepts (older).
- **[Official, Sept 2016]** A 2016 Holly blog post said 12 strategies were "determined overnight" for the day (9 long, 3 short). It described "Risk-On" (hold to the close) and "Risk-Off" (predetermined time-in-trade limit) exit modes, with per-strategy backtested win rates (for example, "Headwind" short at 70.0%). — [Trade Ideas Holly blog (2016 post served at /holly/)](https://www.trade-ideas.com/holly/)

### Inferences
- Holly is a regime-adaptive strategy selector over a fixed rule library, not a predictive ML model of individual stocks. A competitor can reproduce the architecture: a nightly walk-forward backtest of a strategy library, a gate on win rate or profit factor, and publishing the day's active strategies with entry, stop, target and time-stop.
- Signals are a clear buy or short call with an entry and stop. This makes them easy to evaluate objectively if all signals are logged, and it is exactly where Trade Ideas' disclosure is weakest (see section 3).
- The 60% win-rate / 2:1 profit-factor gate is an older marketing claim. The current docs give no thresholds.

### Gaps
- Current (2026) selection thresholds, lookback window length and minimum trade counts are not published.
- No authoritative official description of how Holly Grail, Holly 2.0 and Holly Neo differ was found. The official guide only says each Segment has different strategies.
- The exact target and time-exit rules per strategy are shown only inside the app ("consult the main AI window").

## 3. Holly AI: published performance and the evidence behind it (hypothetical vs real, disclaimers, audits, controversies)

### Takeaway
No independently audited, complete track record of Holly exists. Trade Ideas' current public "Holly Records" are cherry-picked winners measured from signal price to the session's best price ("profit potential"), not realized P&L. Its 2018 headline (+54% in H1 2018 vs SPY +3%) came from a simulated $1M portfolio with no slippage, a 44.9% win rate and no audit. The 2024/2025 win-rate figures quoted online (62–68%) trace back to low-quality or competitor sites that I could not confirm against a primary Trade Ideas document. The one independent mainstream reviewer (StockBrokers.com, June 2026) says the results "appear cherry-picked". I found no regulatory action against Trade Ideas.

### Cited Findings
- **[Official, 2026] Holly Records page:**
  - Calculation method: figures are "profit potential", measured "from Holly AI's signal price to that session's high (buy signals) or low (short signals)", and are "moves our premium subscribers could have captured, not realized profits".
  - Examples are "selected". Every one shown is a winner and no losing trade is shown or quantified, although the page says "Not every signal is profitable and losses can occur."
  - Headline examples: BNAI +2,905% (27 Jan 2026), WOLF +851% (29 Sep 2025), SDOT +676% (26 Jun 2026), NUAI +505% (27 Oct 2025), KRMN +22.5% (6 Nov 2026), QMCO +101.5% swing (25 Sep 2026).
  - The page says Holly "does not place trades, manage money, or give financial advice."

  — [Holly Records (trade-ideas.com/holly-records redirects to tradeideas.lpcontent.net)](https://tradeideas.lpcontent.net/holly-records)
- **[Official, 2026]** Homepage footer: "Holly AI signals shown above are selected examples. Results are not typical." and "Past results, including backtests, don't guarantee future results." The example shown is a CYPH buy at $1.42 dated 21 Aug 2026. — [Trade Ideas homepage](https://trade-ideas.com/)
- **[Official, Aug 2018] Simulated portfolio:**
  - Results: H1 2018 net +54% after commissions (Risk-On), gross +61%, Risk-Off +17%, versus SPY +3.0%. A "maximum alpha" of 76% assumed perfect mode choice for each trade.
  - Trade stats: 1,811 trades, 44.9% winners, profit factor 1.77, Sharpe 5.92.
  - Assumptions: $1M start, about $80k per trade, $0.0075/share commission. Slippage was not factored in. It assumes shares are available to short and holds nothing overnight.
  - Method: described as paper trades (not a backtest) with inception 4 Jan 2016. No third-party audit is mentioned.
  - Disclaimer: "Past performance of the simulated portfolio do not foreshadow or guarantee future results."

  — [Trade Ideas press post, 3 Aug 2018](https://www.trade-ideas.com/2018/08/03/our-a-i-managed-simulated-portfolio-smashes-market-benchmarks-for-1st-half-of-2018/)
- **[Official, Sep 2016]** Holly was "+47.8 accumulated points" year-to-date vs SPY +11.9 points (as of 1 Sep 2016). Win rates were described as based on "optimized, backtested scenarios". — [Trade Ideas Holly blog post (2016)](https://www.trade-ideas.com/holly/)
- **[Official]** The Holly guide computes AI-window P&L on 100 shares per trade by default. It does not say whether commissions or slippage are included. — [Holly AI guide](https://www.trade-ideas.com/hollyguide/print.html)
- **[Independent, 15 Jun 2026]** StockBrokers.com says Holly AI's results "appear cherry-picked". It wants the biggest losing trades, win/loss metrics and the weaker strategies disclosed, and notes crowding because "AI signals go to the whole community". — [StockBrokers.com review](https://www.stockbrokers.com/review/tools/trade-ideas)
- **[Competitor, 6 Mar 2026]** TradeAlgo cites "2025 published performance" for Holly: about 25% annual return, about 62% win rate, average winner +1.4%, average loser −0.9%, profit factor 1.8, 5–8 trades per day. It says these assume fills at signal price, no commissions and equal sizing. It also claims a 6-month live test of Holly Grail on Interactive Brokers: +14.2% vs simulated about 12.5%, and a 58% win rate vs 62% simulated. Methodology gaps: no account size, trade count or dates, plus inconsistent annual/6-month figures, and TradeAlgo sells a competing product. — [TradeAlgo review](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)
- **[Low-quality aggregators]** Search results attribute a "68% win rate on daily setups for 2024" to Trade Ideas. The same site elsewhere lists a 41% internal-simulation figure, contradicting itself. The 68% figure is flagged as "not independently audited". I could not find the primary Trade Ideas report behind either number. — [AlphaSignal Holly review](https://alphasignal-56o.pages.dev/blog/trade-ideas-holly-ai-review/) (low reliability)
- **[Affiliate, Nov 2026]** DayTradingToolkit criticises Trade Ideas' marketing for showing "triple-digit gains" without losing trades. It reports no third-party audit, notes that backtested results differ from live because of slippage, latency and liquidity, and calls the nightly parameter choice "black box". — [DayTradingToolkit, Holly explained](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-holly-ai-explained)
- **[User]** One Trustpilot reviewer (6 Apr 2026) called Holly "very weak" and said they don't see the "60% success rate they tout". Another (21 Jun 2026) called it "Not accurate". — [Trustpilot, trade-ideas.com](https://www.trustpilot.com/review/trade-ideas.com)
- **[Official]** Trade Ideas' standard disclaimer says "Trade Ideas is a publisher", that no content is a recommendation, and that "Trading contains substantial risk and is not for every investor." — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **Regulatory:** Searches found no SEC, FTC, NFA or court action against Trade Ideas or Holly. For context, the FTC has sued other trading-education and signal sellers over performance claims, including Warrior Trading ([FTC complaint](https://business.ftc.gov/system/files/ftc_gov/pdf/2023198WarriorTradingComplaint_0.pdf)) and Raging Bull ([Law360](https://www.law360.com/articles/1335222/ftc-says-stock-tip-site-raging-bull-really-a-fraudulent-bear)).

### Inferences
- **Evidence quality, best to worst:**
  1. The 2018 simulated portfolio, which was hypothetical with no slippage but gave full-distribution stats (44.9% win rate, profit factor 1.77).
  2. Third-party-quoted 2025 stats (unverified).
  3. The current "Holly Records", which are peak-price, winners-only and promotional.

  None is audited live performance.
- The 2018 data shows Holly's edge depended on payoff ratio (profit factor 1.77) with a sub-50% win rate. That contradicts the "60%+ win rate" marketing of the same era.
- Measuring to the session high or low overstates achievable returns by construction. A competitor that logs every signal with realistic exits, slippage and losers would beat Trade Ideas on transparency at almost no cost.
- Calling itself a "publisher" appears designed to fall under the US publisher exclusion from investment-adviser registration. That is my inference and is not stated by Trade Ideas.

### Gaps
- I could not locate an official full-year Holly performance report for 2023, 2024 or 2025. The "Holly Performance History" page in the guide was not retrieved.
- No independent audit (for example, a CPA-verified or broker-statement-based track record) of Holly was found.
- Liberated Stock Trader's Trade Ideas lab test and review pages returned HTTP 403, so its Holly testing, if any, could not be checked.

## 4. OddsMaker backtesting: what it can and cannot test, assumptions, limits

### Takeaway
OddsMaker is a no-code event backtester that replays a user's alert/filter scan over recent history. The 2026 pricing page says the last 60 days. You enter user-set commission and per-share slippage, choose dollar- or share-based sizing, and pick exits by hold period, profit target, stop %, session close or exit date for overnight holds. It reports profit factor, win rate, equity and drawdown curves, and per-filter optimisation buckets. It needs TI Premium and cannot test discretionary logic. Historical depth is short compared with dedicated backtesters.

### Cited Findings
- **[Official, 2026]** TI Premium includes "OddsMaker backtesting over the last 60 days". TI Standard has "60-trading-day historical scanning". — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** The OddsMaker user guide:
  - Launch: right-click an Alert Window and choose "Run OddsMaker", then Simulate Buy or Simulate Sell.
  - Inputs: "per trade commission", "per trade slippage per share", Dollars or Shares sizing, Starting Equity, and a "Use Exit Date" option for strategies "holding at least one night".
  - Outputs: Profit Factor, Total Trades, Avg Winner/Loser, Strategy Return, Projected Annual Return, Buying Power Required, a calendar heatmap of daily P&L, equity, drawdown and buying-power charts, and an Optimization tab that buckets results by filter value.

  — [OddsMaker User's Guide](https://www.trade-ideas.com/OddsMaker/Help.html)
- **[Official, learning center]**
  - Exit options are "hold period, profit target, stop percent, or session close".
  - It warns that "Slippage on fast small caps can exceed assumptions" and that "Strategies heavy on discretion outside the window are not fully captured."
  - It advises checking alert count, profit factor, drawdown and consecutive losers; clicking through at least ten random alerts on charts; and forward-testing on paper for about 30 sessions.
  - It claims tests use "months or years of tick and bar history" and that "Historical data depth varies by symbol and subscription", which conflicts with the pricing page's 60 days.

  — [OddsMaker backtesting guide](https://www.trade-ideas.com/learning-center/backtesting-strategy-development/oddsmaker-backtesting-guide/)
- **[Official, via search summary]** A Trade Ideas page reportedly says OddsMaker uses 1-minute candle data rather than tick-by-tick, so results don't fully capture slippage. A saved formula works as a filter on every Pro plan, but testing it in OddsMaker needs TI Premium. — [Trade Ideas, backtest article, 23 Jul 2026](https://www.trade-ideas.com/2026/07/23/backtest-trading-strategy-before-risking-money/) (attribution from search summary; not fetched directly)
- **[Independent]** StockBrokers.com (June 2026) lists "backtesting" as a Premium (Eagle Elite) feature and gives no detail on OddsMaker. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)

### Inferences
- **What it cannot do (inferred from the docs):**
  - It cannot backtest Holly itself (Holly's parameters are proprietary).
  - It cannot handle portfolio-level rules such as correlation, max concurrent positions or sector caps.
  - It cannot test options, multi-leg or non-equity instruments, or anything outside the alert/filter language.
  - It cannot run multi-year walk-forward tests at the 60-day depth.
- A competitor with multi-year intraday NSE/BSE history, tick-accurate fills, default realistic Indian costs (STT, brokerage, exchange fees, GST, stamp duty) and walk-forward testing would surpass OddsMaker on depth and realism.

### Gaps
- The default commission and slippage values (if any) and the exact fill assumption (alert price vs next bar) are not documented in the sources retrieved.
- The 60-day vs "months or years" lookback conflict could not be resolved. The pricing page is the most specific and most recent.

## 5. Automation: Brokerage Plus, auto-trading, Money Machine, brokers, risk controls

### Takeaway
Brokerage Plus provides one-click, chart and automated order routing from TI Pro to Interactive Brokers, E*TRADE, TradeStation and Alpaca, plus an in-house simulator; the homepage also names NinjaTrader. Money Machine (marketed since about September 2025) is the Premium auto-trading engine for user strategies and Holly/Holly Grail signals. It has pre-trade sizing, stop, target and exit timing, daily loss limits and pause/resume rules, and a simulated mode. Platform-wide, 161 million shares were traded through the integrations in September 2026.

### Cited Findings
- **[Official, 2026]** TI Standard includes Brokerage Plus, broker API connections (Interactive Brokers, E*TRADE, TradeStation, Alpaca), one-click trading, order management and a real-time trade simulator with multiple sim accounts. TI Premium adds "Auto trading of your own strategies through Brokerage Plus, in a live account or the simulator" and the "Money Machine Simulator, which places no live orders". The page claims "161M shares traded in September" through brokerage integrations. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** The homepage lists brokerage partners Interactive Brokers, TradeStation, E*TRADE, NinjaTrader "and others". — [Trade Ideas homepage](https://trade-ideas.com/)
- **[Official]** User-guide broker connections: Trade Ideas Simulator, Interactive Brokers, E*TRADE, Alpaca, TradeStation, plus order, position and P/L tabs. — [TI user guide, Features Overview](https://trade-ideas.com/guide/chapter/32/32Features_Overview.html)
- **[Official, Sept 2025]** The Money Machine article:
  - It describes Money Machine as a "completely integrated, end-to-end automated trading engine" covering signal, routing and risk.
  - What it can automate: Holly and Holly Grail signals, custom filter/entry configurations, and a library of AI-generated strategies.
  - Pre-trade risk controls: position sizing, stop-loss, profit objectives and exit timing. Live-account controls: daily loss limits, position-size controls and pause/resume rules.
  - Simulation Mode runs live during market hours on simulated capital, and the page recommends running it for several weeks.
  - It says Money Machine is not "set it and forget it" and needs real-time monitoring and daily log checks.
  - It claims many AI strategies "have historically performed consistently in all types of market environments", with no figures.

  — [Trade Ideas, Money Machine article (23 Sep 2025)](https://www.trade-ideas.com/2025/09/23/trade-ideas-money-machine-a-new-era-in-automated-trading/)
- **[Official]** Release notes for v5.9.1 say users can load pre-made profiles or configure entry, exit and risk settings manually. — [TI Pro 5.9.1 release notes (PDF)](https://www.trade-ideas.com/MainSite/images/download/release-notes/production-5.9.1.pdf), per search summary
- **[Official, older guide]** The Holly guide lists only manual methods to act on Holly trades: hands-on at your broker, one-click "Trade XYZ" via Brokerage Plus, and chart Buy/Sell buttons. It names the Simulator, Interactive Brokers and E*TRADE. — [Holly AI guide](https://www.trade-ideas.com/hollyguide/print.html)
- **Conflict:** Some older third-party reviews say Holly signals cannot be auto-traded (per search summary). The September 2025 Money Machine article and DayTradingToolkit (Nov 2026) say they can. — [Money Machine article](https://www.trade-ideas.com/2025/09/23/trade-ideas-money-machine-a-new-era-in-automated-trading/); [DayTradingToolkit](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-holly-ai-explained)
- **[Independent, June 2026]** StockBrokers.com lists compatible brokers as Interactive Brokers, TradeStation and E*TRADE. It calls Holly "first-generation" and Money Machine "second generation", and describes setup as technical. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)

### Inferences
- Auto-trading requires the Windows desktop app and a US broker API. None of the brokers listed serves Indian exchanges for this use case. For an Indian platform, the equivalent gap is integration with SEBI-compliant broker APIs (for example, Zerodha Kite Connect, Upstox or Dhan), which is outside Trade Ideas' scope entirely.
- The published risk controls are basic (per-trade sizing, stop, target, daily loss limit, pause). Documented portfolio-level exposure caps, kill-switch details and max-orders-per-minute throttles were not found and could be differentiators.

### Gaps
- The exact Money Machine risk parameter list (max positions, max trades per day, per-symbol caps) was not found in retrieved docs.
- Whether NinjaTrader is supported for equities auto-trading or only for order routing is unclear.

## 6. Charting and other tools vs dedicated charting platforms; AI chart features and charting partners

### Takeaway
Trade Ideas' charting is adequate for execution and scan follow-up. Standard allows 10 charts per screen and Premium 20, with all chart types, indicators, drawing tools and 6-symbol compare. AI overlays include Smart Risk Levels (AI stops/targets) and TI Wave B/S signals. It is not a TradingView-class charting platform, and reviewers cite missing basic indicators and an old-school UI. Charting partners are sold as add-ons: Alphatrends Anchored VWAP and the GoNoGo Trend tool.

### Cited Findings
- **[Official, 2026]** Standard: 10 charts on screen, all chart types, indicators, drawing tools, chart compare (up to 6 stocks), multi-monitor layouts. Premium: 20 charts plus Smart Risk Levels (AI-generated stops and targets on every chart). The free tier allows one chart, plus heat maps, flexible timeframes, PiP charts and TI Wave. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** TI Wave shows "B"/"S" markers on any stock and timeframe, with AI-adjusted moving-average bands. — [Trade Ideas, trading signals](https://www.trade-ideas.com/features/trading-signals/); [What is TI Wave](https://www.trade-ideas.com/learning-center/ai-in-trading/what-is-ti-wave/)
- **[Official]** The homepage still advertises "Wave 2" as coming soon. A 2026 third-party review says Wave 1 is complete and Wave 2 is expanding to more Premium accounts (conflicting status). — [Trade Ideas homepage](https://trade-ideas.com/), per search summary
- **[Independent, June 2026]** Add-ons cost from $49/month (Alphatrends AVWAP indicator and GoNoGo® Trend charting tool). Swing Pick costs $17 and provides five trade ideas by email each Sunday. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)
- **[Official]** User-guide add-ons: Market Explorer, TI Wave, Anchored VWAP, GoNoGo, Layouts & Scans, Stocks Like This. — [TI user guide, Features Overview](https://trade-ideas.com/guide/chapter/32/32Features_Overview.html)
- **[Official]** AI Strategy Lab is marketed as "pre-trained and battle-tested" AI strategies so users don't build their own models. Its FAQ says Holly does the machine learning. — [AI Strategy Lab](https://trade-ideas.com/ai-strategy-lab/)
- **[User/Review aggregate]** Capterra reviewers praise the alerts and pre-made channels but cite a steep learning curve and charting that lacks some basic indicators. — [Capterra, Trade Ideas](https://www.capterra.com/p/253071/Trade-Ideas/), per search summary
- **[Review]** FinMasters lists an "Old School User Interface", "Only US Stock & ETF Coverage" and "No Mobile App" as cons. — [FinMasters review](https://finmasters.com/trade-ideas-review/), per search summary
- **[Competitor, Mar 2026]** TradeAlgo claims "No integrated charting". This is contradicted by Trade Ideas' 2026 pricing page, which lists 10 or 20 charts per screen. — [TradeAlgo](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)

### Inferences
- Many Trade Ideas users pair it with TradingView or a broker platform for charting. The opportunity for a competitor is integrated, high-quality charting where scan hits, AI signals and risk levels are native overlays. Trade Ideas only partly does this (Smart Risk Levels, Wave, Holly entry arrows).

### Gaps
- I found no independent charting benchmark specific to Trade Ideas. Liberated Stock Trader's time-to-chart figure for Trade Ideas was not visible in snippets.
- I found no evidence of a TradingView chart-library integration or other charting partnership beyond the add-ons.

## 7. Market coverage, data feeds and latency

### Takeaway
Coverage is US equities and ETFs: about 8,000+ symbols, premarket from 4:00 am ET and after-hours to 8:00 pm ET. Canadian exchanges were added in 2006, but 2026 reviews describe it as US-only. There is no evidence of India or other international markets. Trade Ideas publishes no exchange-to-alert latency figure, only a 37 ms example round trip from client to server. Data vendors and feed type (SIP vs direct) are undisclosed.

### Cited Findings
- **[Official, 2026]** Real-time data for paid plans covers premarket (4:00–9:30 am ET) and after-hours (4:00–8:00 pm ET). The free tier is 15-minute delayed. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Official]** Trade Ideas says it scans "8,000+" US stocks in real time. — [Trade Ideas, real-time stock scanning](https://www.trade-ideas.com/learning-center/stock-scanning/real-time-stock-scanning/)
- **[Official, Oct 2026]** The TI Pro toolbar shows client-to-server round-trip time. The example given is 37 ms, from one computer at one moment. The page says this is not trade-to-alert time and not a guarantee. It names no data vendor and does not say whether feeds are SIP or direct. — [How fast is Trade Ideas](https://www.trade-ideas.com/how-fast-is-trade-ideas/)
- **[Official, 28 Mar 2006]** Canadian exchanges were added, giving Canadian traders the same real-time price and volume alerts, included in existing plans. — [Trade Ideas, Canada exchanges (2006)](https://www.trade-ideas.com/2006/03/28/canada-exchanges-now-accessible-in-trade-ideas/); [Finextra](https://www.finextra.com/pressarticle/8686/trade-ideas-adds-canadian-stock-data-to-idea-generation-platform)
- **[Third-party broker]** CIBC Investor's Edge offers a "Trade Ideas" tool that "filters through thousands of securities in the Canadian and U.S. markets". This may be a white-label or partner product, not TI Pro. — [CIBC Investor's Edge](https://www.investorsedge.cibc.com/en/learn/investing/stocks/find-stocks-using-trade-ideas.html)
- **[Affiliate, Nov 2026]** Holly and the platform cover "U.S. equities and ETFs only". — [DayTradingToolkit](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-holly-ai-explained)
- **[Competitor, Mar 2026]** Coverage is US equities, "monitoring 8,000+ stocks"; no crypto, forex or futures; no options flow or dark-pool data. — [TradeAlgo](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)

### Inferences
- Trade Ideas has zero India coverage (NSE/BSE). For an Indian-market platform, the competitive overlap is in feature design, not data. An Indian competitor would scan a smaller liquid universe (roughly 2,000–2,500 actively traded NSE equities plus F&O; this figure is not researched here), which makes sub-second full-universe refresh technically easier to match.

### Gaps
- Whether TI Pro still offers Canadian (TSX/TSXV) data in 2026 is unconfirmed. 2026 sources say US only, and the official 2006 release says Canada is included.
- I found no independent exchange-to-alert latency measurement.

## 8. Platforms (Windows desktop vs web vs mobile) and 2023–2026 changes and new AI features

### Takeaway
The full product, TI Pro, is a Windows desktop app; Mac users run it through Parallels. A browser "Web Dashboard" covers dashboards, Top Lists and charts, but Holly, Money Machine, OddsMaker and custom strategies are desktop-only. There is no native mobile app, only the web dashboard in a phone browser. Additions in 2025–2026 include Money Machine automation (about Sept 2025), the AI Assistant (natural-language and voice scan building, about July 2026), AI Strategy Lab, TI Wave chart signals with Wave 2 rolling out, Smart Risk Levels, and the rebranded 2026 plans TI Free, TI Standard and TI Premium.

### Cited Findings
- **[Official]** Platforms: Web Dashboard in a browser, TI Pro on Windows, Mac via Parallels. — [Trade Ideas homepage](https://trade-ideas.com/)
- **[Official, 2026]** TI Free covers Market Dashboards "in any browser, including phones" with 15-minute delayed data, and scans, screeners and quote windows are pre-built only. Standard and Premium are described as the "Windows app". — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Independent, June 2026]** The web version is "straightforward and fairly easy to use". The desktop version is "more advanced" with "a steep learning curve". Holly AI, Money Machine, backtesting and custom strategies are only on desktop. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)
- **[Review, via search summary]** There is no native phone app, and the company has said one is "in the works". — [FinMasters](https://finmasters.com/trade-ideas-review/)
- **[Official]** TI Pro v5.9.2 beta release notes mention easier onboarding for the AI Assistant. — [TI Pro beta 5.9.2 notes (PDF)](https://www.trade-ideas.com/MainSite/images/download/release-notes/beta-5.9.2.pdf), per search summary
- **[Official]** The AI Assistant (plain-English and voice scan building, chart-aware) is included in TI Pro on every plan. — [AI Trading Assistant](https://www.trade-ideas.com/ai-trading-assistant/)
- **[Official]** The pricing page separates "Holly AI signals" from the "AI Assistant". — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)

### Inferences
- A web-first or cross-platform competitor with full functionality, including backtesting and automation in the browser and on mobile, would beat Trade Ideas' biggest structural limitation (Windows-only power features).

### Gaps
- No official release dates were found for AI Strategy Lab or Smart Risk Levels.
- The current TI Pro production version number as of November 2026 was not confirmed.

## 9. Pricing tiers (2026) and what each includes

### Takeaway
As of the 2026 pricing page, Trade Ideas has three plans:
- **TI Free:** delayed data, web only.
- **TI Standard:** $127/month, or $89/month billed annually ($1,068/yr). Real-time scanning, charts, Brokerage Plus and simulator.
- **TI Premium:** $254/month, or $178/month billed annually ($2,136/yr). Adds Holly, OddsMaker, auto-trading and Money Machine.

These replace or rename the older golf-themed plans: Par (free), Birdie (Standard) and Eagle Elite (Premium), still named that way in June 2026 reviews.

### Cited Findings
- **[Official, © 2026]** Full tier detail:
  - **TI Free:** email signup, no card. Web dashboards with 15-min delayed data, heat maps, PiP charts, TI Wave, one chart, pre-built scans only. No Holly, OddsMaker, Brokerage Plus or sim.
  - **TI Standard:** $127/mo monthly, or $89/mo billed $1,068/yr ("saves $456").
  - **TI Premium:** $254/mo monthly, or $178/mo billed $2,136/yr ("saves $912"). Labelled "Most popular".
  - Annual billing is labelled "save up to 30%".

  — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- **[Independent, 15 Jun 2026]** The old plan names were Par Plan (free; delayed data, Stock Race, PiP charts), TI Basic/Birdie Bundle ($127/mo or $89/mo annual) and TI Premium/Eagle Elite ($254/mo or $178/mo annual). Add-ons cost from $49/mo, and Swing Pick costs $17. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)
- **[Affiliate]** TheGodFunded checked prices on 9 Oct 2026: Standard $127 or $1,068/yr, Premium $254 or $2,136/yr. — [TheGodFunded](https://thegodfunded.com/en/tools/trade-ideas/), per search summary
- **[Competitor, Mar 2026]** TradeAlgo quotes Premium at $167/month, which conflicts with the official $178 annual-equivalent and $254 monthly prices. It may reflect a promotion. — [TradeAlgo](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)
- **[Official]** An "October sale 2026" promotional page exists (not retrieved). — [Trade Ideas October sale](https://www.trade-ideas.com/ti-october-sale-2026/)

### Inferences
- The effective cost of the AI and automation features is $2,136 to $3,048 per year (about ₹1.8–2.6 lakh at roughly ₹85/USD; exchange rate assumed, not researched). This sets a high price anchor that an Indian personal platform can undercut massively.

### Gaps
- Whether the free trial or "TI Free" includes any real-time data, and the terms of the October 2026 sale, were not confirmed.

## 10. Strengths, weaknesses and recurring user complaints

### Takeaway
**Strengths:** depth and speed of the streaming scanner (310 alerts and 249 filters, tick-level), ready-made channels, a unique visual layer (Stock Race, Market Pulse), and an integrated pipeline from scan to backtest to sim to broker to auto-trade.

**Weaknesses and complaints:**
- High price.
- Steep learning curve and a dated Windows UI.
- No Mac-native or mobile app.
- US-only coverage.
- Mediocre charting.
- Crowded signals (everyone gets the same Holly alerts).
- Cherry-picked and opaque AI performance marketing.
- Mixed support experiences.

### Cited Findings
- **[Independent, June 2026]** StockBrokers.com ratings: Overall 4.5/5; Features 5.0; Ease of Use 3.5 (lowest); Cost 4.0. Pros: AI signals, Stock Race and Market Pulse visuals, Scope 360. Cons: steep desktop learning curve, clunky repetitive web modules, crowded trades, cherry-picked Holly results. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trade-ideas)
- **[Independent, proprietary benchmark]** Liberated Stock Trader's lab test gives Trade Ideas a composite score of 4.52 (AA) vs a benchmark median of 4.21, and a Speed & Use index of 4.50 vs a median of 4.50. — [LST Trade Ideas benchmark lab test](https://www.liberatedstocktrader.com/trade-ideas-benchmark-lab-test/), via search snippet (page returned 403 to direct fetch)
- **[Official]** Trade Ideas cites awards: Investopedia Best Short Term Stock Screener 2024, a StockBrokers.com 2026 badge, a Benzinga 2023 badge, and Inc. 5000 six years (2017–2022). — [Trade Ideas homepage](https://trade-ideas.com/)
- **[User] Trustpilot:**
  - Score 3.9/5 from 51 reviews, with 35% one-star and 10% two-star.
  - Complaints:
    - Holly accuracy, e.g. "very weak" (Apr 2026) and "Not accurate" (Jun 2026).
    - Usability: "This website is not usable" (Jun 2026).
    - Support: "Chat was a disaster" (Oct 2026).
    - An "outdated and complicated user guide" (Jul 2024).
    - Value: "Free tools even better" (Jun 2026).
  - The company had not replied to negative reviews.

  — [Trustpilot](https://www.trustpilot.com/review/trade-ideas.com)
- **Conflicting Trustpilot figures:** Bullish Bears reported a 2.2 TrustScore ("Poor", March 2026) and Tradersunion reported 3.6. TheGodFunded flagged that 8 of 10 five-star reviews came from accounts with only one or two reviews. — [Bullish Bears](https://bullishbears.com/trade-ideas-scanner/); [Tradersunion](https://tradersunion.com/reviews/trade-ideas-com/); [TheGodFunded](https://thegodfunded.com/en/tools/trade-ideas/), per search summary
- **[User/Review]** Capterra reviewers praise alerts and pre-made channels ("best for stocks"). They cite a "steep learning curve" and charting lacking basic indicators. — [Capterra](https://www.capterra.com/p/253071/Trade-Ideas/), per search summary
- **[Affiliate]** DayTradingToolkit lists cons: cherry-picked marketing, crowding on thin small-caps, a complex Windows platform, black-box nightly parameters, and backtest vs live divergence. — [DayTradingToolkit](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-holly-ai-explained)
- **[Competitor]** TradeAlgo's criticisms: a dated interface with a 2–4 week learning curve, Holly skewed to small and mid caps, poor fit for swing traders or accounts under $25K (the US pattern-day-trader rule), and no options flow or dark-pool data. — [TradeAlgo](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)
- **Reddit:** Searches did not surface primary r/Daytrading or r/algotrading threads. Affiliate sites characterise Reddit sentiment as positive on scanning but negative on learning curve and cost. — [search summary of review sites, e.g. Bullish Bears](https://bullishbears.com/trade-ideas-scanner/) (low reliability)

### Inferences
- The most defensible weak points to attack are:
  1. Transparency of AI performance (publish complete logs including losers).
  2. Ease of use, with a modern UI and natural-language setup.
  3. Platform reach (web and mobile parity).
  4. Price.
  5. Signal crowding, through personalised or less-shared signals.

### Gaps
- No primary Reddit threads were retrieved, so first-hand forum sentiment is under-sourced.
- Benzinga and Investopedia full reviews were not retrieved, and Investopedia is known only via Trade Ideas' award claim.

## 11. Measurable benchmarks a competitor could match or beat

### Takeaway
The concrete, published numbers are:
- 310 alerts / 249 filters
- tick-level alert firing
- 15-second Top List refresh
- an example 37 ms client-to-server round trip
- 8,000+ symbols
- 60 trading days of historical scanning and OddsMaker backtesting
- 10 or 20 charts per screen
- 5–25 Holly trades per day from 60+ nightly-reoptimised strategies
- a default 100-share AI risk size
- about 3% typical Holly stop

The 2018 simulated Holly baseline (44.9% win rate, profit factor 1.77, no slippage) is the only full-distribution AI stat with a stated method. No exchange-to-alert latency or stocks-per-second figure is published.

### Cited Findings
- 310 alerts, 249 filters, 56 scanner pages; Top Lists refresh every 15 s; alerts fire on every qualifying trade; 37 ms example round trip (not trade-to-alert). — [How fast is Trade Ideas](https://www.trade-ideas.com/how-fast-is-trade-ideas/)
- 60-trading-day historical scanning; OddsMaker covers the last 60 days; 10 charts (Standard) or 20 (Premium); chart compare of up to 6 symbols. — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- 8,000+ US stocks scanned in real time. — [Trade Ideas, real-time stock scanning](https://www.trade-ideas.com/learning-center/stock-scanning/real-time-stock-scanning/)
- Holly: "over 60 strategies" backtested nightly, usually 5–25 trades per day, 100-share default AI risk size. — [Holly AI guide](https://www.trade-ideas.com/hollyguide/print.html)
- Holly stop is usually about 3% from entry. — [Trade Ideas homepage](https://trade-ideas.com/)
- 2018 simulated Holly: 1,811 trades in H1, 44.9% win rate, profit factor 1.77, +54% net on $1M at about $80k per trade, no slippage, unaudited. — [Trade Ideas, Aug 2018](https://www.trade-ideas.com/2018/08/03/our-a-i-managed-simulated-portfolio-smashes-market-benchmarks-for-1st-half-of-2018/)
- Older gate claim: only strategies with a success rate above 60% and a 2:1 profit factor are shown the next day, chosen from about 1 million overnight simulated trades over 55 concepts (undated, about 2016–2017). — [Equities.com](https://www.equities.com/news/holly-float-on-leads-7-other-trade-ideas-3), via search snippet
- 2025 Holly stats quoted by a competitor (about 62% win rate, PF 1.8, about 25% annual return, simulated fills at signal price, no commissions) are unverified. — [TradeAlgo](https://www.tradealgo.com/trading-guides/ai-trading/trade-ideas-review)
- AI Assistant: a live whole-market Top List in under 6 seconds from a prompt (third-party recorded test). — [DayTradingToolkit AI Assistant](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-ai-assistant), per search summary
- 161M shares traded in Sept 2026 through brokerage integrations (adoption metric). — [Trade Ideas pricing](https://www.trade-ideas.com/pricing/)
- LST lab composite score 4.52 (AA) vs median 4.21. — [LST benchmark](https://www.liberatedstocktrader.com/trade-ideas-benchmark-lab-test/), via snippet

### Inferences
- **Easy wins for a competitor:**
  - Screener refresh well under 15 s (1–5 s or event-driven).
  - Backtest history longer than 60 days, with realistic Indian cost models.
  - Full, auditable AI signal logs that include losers and realized exits, with slippage, instead of peak-price "profit potential".
  - A published end-to-end tick-to-alert latency (Trade Ideas publishes none).
  - Full functionality on web and mobile.
- **Hard to match:**
  - A 20+ year scanner tuned for US microstructure with 559 alert/filter primitives.
  - Integrated scan, backtest, sim, auto-trade and multi-broker routing.
  - An established community.

  The realistic target is depth in a smaller universe (Indian equities and F&O) rather than breadth.

### Gaps
- No independently measured tick-to-alert latency, stocks-per-second throughput or scan CPU benchmark exists for Trade Ideas in the sources found.
- No audited Holly win rate exists. All win-rate figures are vendor or third-party claims, hypothetical or simulated.
- Indian regulatory constraints (for example, SEBI rules on retail algo trading and on advertising past performance) were outside this assignment and were not researched.
