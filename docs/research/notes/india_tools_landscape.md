# Indian Retail Trading-Tool Landscape (NSE/BSE Equities and F&O), as of November 2026

Research date: 11 Nov 2026. Most prices come from third-party comparison pages checked in Oct 2026 or vendor help pages, not live checkout pages. Treat every price as "last published", and re-check before quoting. Vendor blogs that compare themselves with competitors (AlgoTest, Strike, Tapetide, OneTradeJournal, Neostox, Intraday Lab) are flagged where their claims matter.

## 1. TradingView in India: NSE/BSE data, cost, broker integrations, Pine Script, screeners, alerts

### Takeaway
Around 18 to 20 Sept 2026, free (Basic) TradingView accounts in India started getting 15-minute-delayed NSE data. Real-time NSE now needs a paid plan (Essential from about ₹995/month billed annually) or a linked broker. BSE real-time is a separate paid add-on. Many Indian brokers support trading from TradingView charts (Dhan, Fyers, Angel One, Upstox, Kotak Neo, Paytm Money and others). Zerodha, the largest broker, does not support order routing from TradingView.com. It embeds TradingView-based charts inside Kite instead.

### Cited Findings
**Data entitlement change (Sept 2026)**
- AlgoTest's blog, dated 18 Sept 2026, says free TradingView users in India now see a "D" (delayed) marker on NSE/BSE symbols, with prices 15 minutes behind. It calls this a data-entitlement change, not an outage, and says logging out and back in does not fix it. US stocks and crypto are unaffected. — [AlgoTest blog](https://algotest.in/blog/tradingview-charts-showing-delayed-data/)
- The same article reproduces TradingView's futures/options entitlement table: NSE is real-time by default for non-professional users, NSE professional users must sign an exchange agreement, and BSE is delayed for all users with real-time sold as a paid package. The article notes that cash-equity rules may differ and that traders report inconsistent results. — [AlgoTest blog](https://algotest.in/blog/tradingview-charts-showing-delayed-data/)
- On Zerodha's TradingQnA forum, posts dated 20 Sept 2026 describe the switch as sudden. One user notes that TradingView's own docs still say NSE real-time is available by default for non-professionals. A paid user reported that live NSE data came back only after accepting a "live NSE data" confirmation prompt. Workarounds suggested were logging in via a supported broker and watching GIFT Nifty, which is still live. No Zerodha staff replied. — [TradingQnA thread](https://tradingqna.com/t/why-is-no-one-talking-about-this-tradingview-data-delay/198284)
- A FYERS community post, dated 19 Sept 2026 per search metadata, reports the same NSE delay and pitches FYERS' TradingView-based charts as the workaround. — [FYERS community](https://fyers.in/community/t/nse-data-delayed-on-tradingview-here-s-what-you-can-do/24313)
- Older guides from April 2026 or earlier say free users had a 1 to 5 minute lag, or real-time data, with paid plans "from ₹1,125/month". These are now out of date. — [TradingZenith guide (Apr 2026)](https://tradingzenith-net.pages.dev/artigos/tradingview-india-guide)
- NSE published a new domestic market-data price list effective 1 Apr 2026. These are vendor and licensee fees, not retail prices, but they are the upstream cost behind redistribution decisions like TradingView's. — [NSE pricing file](https://nsearchives.nseindia.com//web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf)

**TradingView India plan prices and limits (checked 14 Oct 2026, INR, before tax)**
- Basic ₹0. Essential ₹1,295/month monthly or ₹995/month billed annually (₹11,940/yr). Plus ₹2,595 or ₹2,095. Premium ₹5,095 or ₹4,195. Ultimate's price is unclear because the source's data conflicts. Annual prices are labelled "special" and may not be the renewal price. — [OneTradeJournal: TradingView plans India](https://onetradejournal.com/platforms/tradingview-plans-india)
- Limits by tier (charts per tab / indicators per chart / price alerts / technical alerts / intraday bars): Basic 1/2/3/none/5,000; Essential 2/5/20/20/10,000; Plus 4/10/100/100/10,000; Premium 8/25/400/400/20,000 with seconds intervals; Ultimate 16/50/1,000/1,000/40,000 with seconds and tick intervals. — [OneTradeJournal](https://onetradejournal.com/platforms/tradingview-plans-india)
- Real-time NSE is listed as included in paid plans, and free accounts get 15-minute-delayed NSE. BSE stocks and BSE F&O are separate packages, priced in a worked example at ₹422/month and ₹176/month. — [OneTradeJournal](https://onetradejournal.com/platforms/tradingview-plans-india)
- One search summary cites TradingView's coverage page, as checked on 13 Oct 2026, saying real-time NSE is free on Essential or higher and delayed 15 minutes on Basic. — [OneTradeJournal: why market data is delayed](https://onetradejournal.com/platforms/why-market-data-is-delayed)

**Broker integrations (trade from TradingView charts)**
- Dhan was TradingView's "first-ever trading integration partner from India" in 2022, covering stocks and futures on NSE, BSE and MCX. — [TradingView blog: Dhan live](https://www.tradingview.com/blog/en/dhan-live-on-tradingview-34732)
- Since May 2024, Dhan also supports options trading on TradingView.com, with option charts and order placement from the chart. Dhan's post claims coverage of 5 indices and 182 NSE stocks, and Dhan describes it as a global first. Chart features still depend on the user's TradingView plan. — [TradingView blog: Dhan options](https://tradingview.com/blog/en/dhan-features-options-trading-44855); [Finance Magnates (May 2024)](https://www.financemagnates.com/forex/tradingview-integration-expands-dhans-offerings-of-options-trading/)
- Angel One is connected: users click "Trade" on Supercharts, pick Angel One and sign in. Stocks, ETFs, futures and options are supported. — [FX News Group](https://fxnewsgroup.com/?p=45041)
- A check of TradingView's India broker directory on 14 Oct 2026 lists Dhan, FYERS, Angel One, Alice Blue, Bajaj Broking, Kotak Neo, Paytm Money, Share.Market, Motilal Oswal, INDmoney and Upstox. — [OneTradeJournal: brokers connected to TradingView](https://onetradejournal.com/platforms/brokers-connected-to-tradingview)
- Zerodha does not support trading from TradingView.com. A TradingQnA answer says "Not possible… use Dhan", and another thread asks for the feature because Fyers and Dhan already have it. Kite instead embeds a TradingView-based chart with its own indicator library, up to 8 charts together and 10 saved layouts. — [TradingQnA: Zerodha integration](https://tradingqna.com/t/zerodhas-integration-with-tradingview/177136); [OneTradeJournal](https://onetradejournal.com/platforms/tradingview-plans-india)
- FYERS offers TradingView with real-time data through FYERS and order placement from TradingView. Its "API Bridge" turns TradingView alert/webhook signals into FYERS orders. FYERS' April 2026 recap says TradingView and Chartink webhooks can drive automated workflows, with execution inside FYERS. — [FYERS support: API Bridge](https://support.fyers.in/portal/en/kb/articles/how-to-integrate-fyers-api-bridge-with-tradingview); [FYERS Product Recap Apr 2026](https://fyers.in/community/t/fyers-product-recap-april-2026/12280)
- Connecting a broker does not always restore live data on TradingView's own chart. Broker apps show live prices under the broker's own exchange entitlement. — [AlgoTest blog](https://algotest.in/blog/tradingview-charts-showing-delayed-data/)

**User friction**
- A Neostox post dated 24 Aug 2026 lists these complaints:
  - The free plan blocks a fourth indicator ("Upgrade to add more indicators").
  - Shared screenshots carry a watermark.
  - Bar Replay for manual backtesting is paywalled.
  - Billing is in USD, so users pay forex markup. This conflicts with the INR prices listed above, and Neostox sells a competing product.
  - The chart lags the broker terminal by a few seconds on fast timeframes.
  
  — [Neostox blog](https://blog.neostox.com/charting/charting-platform-friction-indian-traders)
- GoCharting's India plan reportedly includes real-time NSE and MCX data even on its Free plan. This positions it as a free-real-time alternative after the TradingView change. — [OneTradeJournal: TradingView vs GoCharting](https://onetradejournal.com/platforms/tradingview-vs-gocharting)
- A TradingQnA thread title asks whether any broker allows orders directly from TradingView under the new API IP-whitelisting rules. Webhook-to-broker automation is now harder because of static-IP requirements (see section 3). — [TradingQnA thread](https://tradingqna.com/t/tradingview-india-api-ip-whitelisting-is-any-broker-allowing-orders-directly-from-tradingview-platform/192888)

### Inferences
- The change for free users makes real-time NSE charting a paid feature on TradingView (about ₹12k/yr minimum) unless the trader uses a broker's embedded TradingView-style chart. A new Indian platform that offers free or cheap real-time NSE charts, via a broker feed or its own licence, would have a clear acquisition hook. Exchange licensing costs, per the NSE price file, are the constraint.
- Zerodha's large user base cannot trade from TradingView.com. That leaves room for any tool that combines TradingView-grade charting with Kite execution, for example through Kite Connect at ₹500/month.
- Under SEBI's 2026 algo rules, TradingView webhook to broker API routing now needs a static IP and an empanelled or registered app. Hobbyist webhook bots built before 2026 likely broke.

### Gaps
- I did not retrieve TradingView's own official India pricing page or data-coverage page. The prices come from a third-party snapshot.
- TradingView has not published an official explanation of the Sept 2026 change, and I found none.
- I found no India-specific data on Pine Script (for example limits on NSE options-chain data in Pine), TradingView's stock screener coverage of NSE fundamentals, or whether webhook alerts need a paid plan in India. I am not stating these from memory.

## 2. Scanners and research platforms: Chartink, StockEdge, Screener.in, Trendlyne, Tickertape

### Takeaway
Indian scanning is split. Chartink is the default free technical scanner, with real-time data, 1 to 3 minute timeframes and alerts behind ₹780/month. Screener.in dominates fundamentals at ₹4,999/yr. Trendlyne sells scored research (DVM) plus screener backtests, from ₹390/month or ₹2,990/yr up to about ₹11,900/yr. Tickertape Pro (₹399/month, ₹2,999/yr) and StockEdge (₹399/month to ₹2,499/month) target investors. Almost none of them refund.

### Cited Findings
**Chartink**
- Free tier: scans and charts at 5-minute-plus timeframes, with data delayed about 5 minutes. No custom alerts. — [Strike review of Chartink](https://www.strike.money/reviews/chartink)
- Premium: ₹780 for 30 days, ₹2,220 for 90 days, ₹8,500 for 365 days, tax-inclusive. It adds real-time scans, 1/2/3-minute timeframes, private scans and dashboards, and SMS, email or webhook alerts. No refund once activated and no trial. — [Tapetide price table (24 Oct 2026)](https://tapetide.com/compare/stock-research-subscription-prices-india)
- The scan builder uses a grammar-style syntax such as "Close > 500", with technical filters (RSI, MACD, EMA) and some fundamental ones (P/E, book value). Chartink claims historical data "from the 1980s" for backtesting. — [Strike review](https://www.strike.money/reviews/chartink)
- There is no official Android or iOS app (browser-based), and support is email-only. Complaints: free-tier delay causing missed trades, questions about whether Premium is worth it, billing and subscription disputes on JoinChargeback (3.2/5), and ads and glitches in the free version. — [Strike review](https://www.strike.money/reviews/chartink). Strike is a competitor and recommends itself.
- One third-party comparison claims Premium allows only 2 custom scans. This is unverified and conflicts with Chartink's public scan library model. — [Chartink pricing search summary via Strike/Tapetide](https://tapetide.com/compare/chartink-alternatives)
- FYERS lets Chartink webhooks trigger orders, so Chartink scans can drive execution through FYERS. — [FYERS Product Recap Apr 2026](https://fyers.in/community/t/fyers-product-recap-april-2026/12280)

**Screener.in (fundamentals)**
- Premium is annual only, at ₹4,999 including GST. Stock alerts go from 10 to 800, screen alerts from 2 to 75. It adds more ratios and comparison columns, data downloads, multiple watchlists and ₹500 of AI credits. Full refund within 48 hours, no trial. — [Tapetide (24 Oct 2026)](https://tapetide.com/compare/stock-research-subscription-prices-india)

**Trendlyne**
- GuruQ: ₹390/month or ₹2,990/yr (₹1,890 with coupon). It has 1,758 screener parameters, forecaster estimates for 1,000+ companies, 200 backtests/yr, 2,000-row downloads and 7 AI credits/month. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)
- StratQ: ₹9,900/yr (₹5,900 with coupon). It has 3,512 parameters, 15-minute intraday technicals, 1,200 backtests, unlimited downloads and Excel Connect. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)
- PRO (India + US): ₹1,500/month or ₹8,900/yr. PRO PLUS: ₹2,000/month or ₹11,900/yr, adding "SmartOptions" for F&O. A separate MCP/AI connector costs ₹299 or ₹499/month. No refund, no trial. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)
- DVM scores rate Durability, Valuation and Momentum from 0 to 100. Above 55 is Good, 35 to 55 Mid, below 35 Bad. Durability and Valuation update intraday as new results or shareholding data arrive, and Momentum updates at end of day. Combinations get labels such as "Strong Performer". Alerts work through saving a DVM-based screener and setting an alert on it. — [Trendlyne help: DVM](https://help.trendlyne.com/support/solutions/articles/84000347982-what-is-the-trendlyne-dvm-score-and-how-does-it-work-)
- Trendlyne publishes performance claims for DVM strategies from its own backtests, such as "DVM investing strategies beat benchmarks by big margins". These are not independently verified. — [Trendlyne post](https://trendlyne.com/posts/3808786/as-investors-seek-alpha-dvm-investing-strategies-beat-benchmarks-by-big-margins)

**Tickertape**
- Pro: ₹399/month, ₹899 for 3 months, or ₹2,999/yr (offer). It includes analyst forecasts, scorecards, red flags, 100+ metrics (versus 8 free) and 69 premium screener filters, plus data export and no ads. No refund mid-period, no trial. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)

**StockEdge (Kolkata, SEBI RA INH300007493, claims 4M+ registered users)**
- Premium: ₹399/month list (some sources say about ₹250), or about ₹1,499/yr with coupon. It has 500+ ready-made scans, 20 combination scans, only 2 custom scans, sector rotation and CSV downloads. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india); [StockEdge site](https://stockedge.com/)
- Pro: ₹1,499/month or ₹5,999/yr with coupon, adding 50 custom scans, chart patterns and industry rotation. Club: ₹2,499/month or ₹11,994/yr with coupon, adding Stock AI, SEBI-registered research ideas and analyst access. No refunds. Monthly plans must be cancelled 2 days before renewal. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)

**Others on the same price grid (Oct 2026)**
- Moneycontrol PRO: ₹99/month or ₹499/yr (coupon) for scanners, SWOT and forecasts. Super PRO: ₹499/month or ₹2,499/yr, adding trading calls, daily chart patterns and AI WhatsApp alerts. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)
- Other prices: Tijori ₹330/month or ₹3,500/yr; MarketsMojo MojoOne Expert ₹9,999 (14 months); Value Research Stock Advisor ₹9,990/yr. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)
- Zerodha's Streak, which is free for Zerodha users, includes 250+ pre-built technical scanners whose results can be sent as Kite orders. — [Zerodha Z-Connect (17 Jan 2024)](https://zerodha.com/z-connect/?p=368853)

### Inferences
- Fundamentals (Screener.in, Trendlyne, Tickertape) and intraday technical scanning (Chartink, Streak) are served by different products. Users pay for and learn two or three tools. Only Trendlyne bundles a screener backtester, capped at 200 to 1,200 backtests/yr, and it is fundamentals-centric.
- Price anchors for an Indian retail tool: ₹250 to ₹800/month or about ₹2,000 to ₹8,500/yr for a single-purpose tool. ₹1,000 to ₹2,500/month is premium territory.
- Strict no-refund, no-trial policies are the norm (Chartink, Tickertape, Trendlyne, StockEdge). Screener.in's 48-hour refund is the exception. A trial or refund policy would differentiate.

### Gaps
- I did not reach chartink.com/subscription to confirm current prices or any custom-scan cap.
- I found no data on how far back Screener.in or Trendlyne screener backtests go, or whether they handle survivorship (delisted stocks).
- Tickertape's free-versus-Pro screener filter counts beyond the Tapetide snapshot are unconfirmed.

## 3. No-code and algo platforms (Streak, Tradetron, AlgoTest, Dhan, uTrade Algos, Quantiply) and SEBI's retail algo framework

### Takeaway
SEBI's 4 Feb 2025 circular on retail algo trading became fully mandatory on 1 Apr 2026, after running in parallel until 31 Mar 2026. Brokers are now principals for every algo. API orders need static-IP whitelisting, daily 2FA and exchange Algo-ID tagging, and are capped around 10 orders/sec. Third-party platforms must be exchange-empanelled and hosted in broker infrastructure. Of the platforms covered here, AlgoTest says it is NSE/BSE-empanelled. Streak, Dhan and FYERS operate as broker-native tools. Tradetron, still under the shadow of SEBI's 2024 action against 120+ brokers, has an unclear empanelment status.

### Cited Findings
**Framework rules and timeline**
- The core SEBI circular on safer retail participation in algo trading is dated 4 Feb 2025. The full mandate applies from 1 Apr 2026. Brokers are treated as principals and algo providers as their agents. — [Sahi blog](https://www.sahi.com/blogs/sebi-algo-trading-rules-2026-what-every-retail-trader-must-know-before-april)
- Secondary sources say brokers began registering algo products around Oct 2025, and non-compliant brokers were barred from onboarding new retail API clients from 5 Jan 2026. Sources disagree on intermediate milestone dates. — [Mutwo Labs](https://mutwolabs.com/blog/sebi-algo-trading-framework-2026-broker-guide)
- FYERS' implementation, as a primary broker source:
  - Old and new frameworks ran in parallel until 31 Mar 2026, and the new one took effect on 1 Apr 2026.
  - Orders are accepted only from a registered App ID tied to a whitelisted static IP, which can come from an ISP, AWS/GCP or a VPN. A shared static IP is allowed for family.
  - 2FA is required once every trading day, and "continuous refresh-token sessions will not be supported".
  - There is a 10 orders/sec cap.
  - Market orders are converted to Market Price Protection (MPP) orders.
  - Third-party platforms must be empanelled and hosted within the broker's infrastructure.
  
  — [FYERS support](https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026)
- From 1 Apr 2026, every algo order must carry an exchange-issued Algo-ID. Providers must route through registered brokers and cannot connect directly to exchanges. — [RTI Wiki](https://righttoinformation.wiki/sebi-algo-trading-rules-retail-investors-2026); [FlyTradr](https://www.flytradr.com/blog/sebi-algo-trading-rules-retail-traders-india-2026)
- One source says self-coded retail API users under 10 orders/sec are exempt from registration and Algo-ID. Others say every algo order needs a tag. This conflict is unresolved. — [ArthaLearn](https://www.arthalearn.com/blog/sebi-algo-trading-rules-2026) vs [RTI Wiki](https://righttoinformation.wiki/sebi-algo-trading-rules-retail-investors-2026)
- SEBI created "white box" algos (logic disclosed and replicable) and "black box" algos (logic not disclosed). Per Zerodha CEO Nithin Kamath's explainer, black-box sellers need to register as Research Analysts. — [Business Today (8 Feb 2025)](https://www.businesstoday.in/markets/stocks/story/if-youre-selling-algos-zerodhas-nithin-kamath-on-sebis-sweeping-changes-for-retail-traders-463872-2025-02-08); [Zerodha Z-Connect explainer (6 Feb 2025)](https://zerodha.com/z-connect/featured/explaining-the-latest-sebi-algo-trading-regulations)
- The Intraday Lab comparison (4 Apr 2026) labels Streak, Dhan and FYERS as compliant through their brokers and AlgoTest as exchange-empanelled. It says Tradetron's status is not confirmed and users should verify. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)

**Tradetron**
- In Oct 2024, SEBI scrutinised and issued show-cause notices to 120+ brokers over their API association with Tradetron. The issue was marketplace strategies advertised with assured or guaranteed-return-like claims, which a 2022 SEBI circular bars brokers from being associated with. By early 2026 this reportedly moved to adjudication against named brokers. SEBI also floated a settlement scheme. The action targeted brokers, not retail users. — [Business Standard (Oct 2024)](https://www.business-standard.com/amp/markets/news/sebi-scrutinises-brokers-linked-to-algo-trading-with-guaranteed-returns-124100901218_1.html); [Outlook Business](https://www.outlookbusiness.com/markets/sebi-offers-settlement-scheme-for-brokers-under-scrutiny-in-algo-trading-probe); [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- Features: 150+ keywords covering indicators, Greeks, time conditions and position management. It has a strategy marketplace, cloud execution and 70+ brokers, including international ones. Cons: steep learning curve, costs that rise with usage, and marketplace strategies of uneven quality. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- Pricing conflicts across sources:
  - FitGap lists Free ₹0 (10 private strategies, 1 deployable), Retail ₹1,200/month (5 deployed), Retail+ ₹2,500 (12), Creator ₹5,000 (25) and Creator+ ₹9,000 (50). Quarterly billing saves 7% and yearly 17%. MCX and other exchange sets are priced separately. — [FitGap](https://us.fitgap.com/products/tradetron-algo-strategy-marketplace)
  - Intraday Lab gives about ₹300 to ₹500 entry and ₹1,500 to ₹3,000 for heavy use.
  - AlgoTest, a competitor, gives basic ₹1,000 to ₹1,500, advanced ₹3,000+, plus per-strategy marketplace fees. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison); [AlgoTest pricing blog](https://algotest.in/blog/algo-trading-software-price-in-india/)
  
  The official page is tradetron.tech/user/pricing, which was not retrieved. — [Tradetron help](https://help.tradetron.tech/en/article/tradetron-pricing-plans-upgrade-refund-policy-7oisc0/)

**AlgoTest**
- Starter is ₹499/month and includes live deployment. The free tier gives 25 backtests/week and unlimited paper trading. It has a no-code builder, multi-broker support (Zerodha, Angel One, Fyers and others, 20+ in total) and an "RA Algos" marketplace of strategies from SEBI-registered research analysts. — [AlgoTest pricing blog (updated 15 May 2026)](https://algotest.in/blog/algo-trading-software-price-in-india/); [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- AlgoTest was founded in 2021 and is described as having 25,000+ active users and an options focus. Its multi-leg options backtests model slippage, brokerage and STT, including the post-Budget 2026 STT rates. Analytics include Sharpe, max drawdown and Calmar, plus a "simulator" that replays past dates. Per Intraday Lab, AlgoTest is the only no-code platform reviewed that models STT and slippage. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- AlgoTest claims NSE and BSE empanelment as an algo vendor. Third-party lists repeat this, and I did not verify it on the exchange lists. — [AlgoTest: Tradetron alternatives](https://algotest.in/blog/best-tradetron-alternatives-in-2026/)
- AlgoTest claims up to 7.5+ years of historical data. Complaints: options-centric, 1 to 2 hours to learn the condition logic, and some users find live deployment slower than Streak. — [AlgoTest vs Streak](https://algotest.in/blog/algotest-vs-streak/); [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)

**Zerodha Streak**
- Since 17 Jan 2024, Streak has been free with unlimited access for all Zerodha customers, after previously being paid. It offers 250+ scanners, 150+ pre-built strategies, backtest stats and virtual (paper) deployment. In post comments, Streak staff gave limits of 5 live and 15 virtual deployments, with the 5-live cap still in place as of May 2025. — [Zerodha Z-Connect](https://zerodha.com/z-connect/?p=368853)
- Old paid tiers (Basic, Premium, Ultimate at ₹350, ₹630 and ₹980/month on annual billing) are historical and no longer sold to Zerodha users. — [Chittorgarh](https://chittorgarh.com/article/zerodha-streak-review-algo-trading-for-retail/516)
- Limits: Zerodha only, 80+ indicators, a 5-condition cap with no nested logic or multi-timeframe analysis, and no multi-leg options. Strategies are not portable to other brokers. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)

**Broker-native APIs and tools**
- Kite Connect (Zerodha): the "Personal" tier is free for orders, GTT, alerts and portfolio, but has no market data. "Connect" is ₹500/month per API key with live and historical data, down from ₹2,000 in 2025. For Oct 2026 there are two conflicting accounts. One says Connect users generating ₹2,000+ in brokerage per month get 500 developer credits worth ₹500. The other says the fee is waived for active traders. — [Zerodha support: API charges](https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/kite-api/articles/what-are-the-charges-for-kite-apis); [TradingQnA: free Kite Connect for active users](https://tradingqna.com/t/free-kite-connect-subscription-for-active-users/198623)
- Dhan: free DhanHQ API, a basic strategy builder and paper trading. It was early to implement static IP, 2FA and order tagging. Limits: little condition complexity and basic backtesting. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- FYERS:
  - Free API (Python `fyers-apiv3`).
  - "FYERS Automate", a no-code builder with backtest before deploy.
  - API Bridge for TradingView and Chartink webhooks.
  - 2026 API additions: C and Go SDKs, order and trade history endpoints, a Greeks/IV flag on the option chain API, and screeners via API.
  - "FYERS Prime" plan with higher API limits and deeper history.
  
  — [FYERS algo trading page](https://fyers.in/offerings/algo-trading); [FYERS: screeners on API](https://fyers.in/whats-new/introducing-screeners-on-fyers-api); [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)

**uTrade Algos and Quantiply**
- uTrade Algos lists four tiers: Beginner, Pro, Wizard and Expert. The entry "Prarambh" plan is ₹999/month on GetApp and Software Advice, with a 7-day trial. AlgoTest claims uTrade's paid plans were in "limited rollout" or free as of April 2026, which is self-contradictory. — [GetApp](https://www.getapp.com/finance-accounting-software/a/utrade-algos); [AlgoTest pricing blog](https://algotest.in/blog/algo-trading-software-price-in-india/)
- Quantiply is described only as "institutional-grade, higher cost". No published retail pricing was found. — [AlgoTest pricing blog](https://algotest.in/blog/algo-trading-software-price-in-india/)

**Market context**
- Moneycontrol reported that, after SEBI's F&O crackdown, brokers see algo trading as a new revenue stream. — [Moneycontrol via TradingView news](https://it.tradingview.com/news/moneycontrol:20cb68704094b:0-as-sebi-cracks-down-on-f-o-brokers-eye-algo-trading-as-new-revenue-stream)

### Inferences
- The 2026 framework raises the bar for any new Indian algo product. It must either be empanelled with NSE/BSE and hosted in each broker's infrastructure, or run as a "personal use" tool on the user's own static IP and API key. Daily 2FA rules out fully unattended multi-day bots, and the 10 OPS cap rules out HFT-style retail bots.
- Selling strategies is now regulated. Black-box strategy sellers effectively need RA registration, and marketplaces carry the Tradetron precedent. A platform that shows only white-box, user-built logic with verified stats is lower-risk.
- Broker-native tools (Streak, Dhan, FYERS Automate) are free but lock users in. Broker-agnostic platforms (AlgoTest, Tradetron, uTrade) charge ₹500 to ₹2,500+/month, plus Kite Connect at ₹500/month for Zerodha users.

### Gaps
- I did not retrieve SEBI's 4 Feb 2025 circular or the NSE/BSE empanelled-vendor lists, so empanelment status (AlgoTest, Tradetron, uTrade, Quantiply) is unverified from primary sources.
- I could not confirm Tradetron's current official INR prices.
- I found nothing reliable on Quantiply's 2026 product or pricing.
- I found no hard data on how many retail algo users or platforms dropped off after 1 Apr 2026.
- uTrade's "Dhan options trader / TradingView integration" detail beyond Dhan's own posts was not found.

## 4. Options analytics: Sensibull, Opstra, Quantsapp, Dhan, Kite, FYERS

### Takeaway
Options analytics pricing ranges from free to ₹8,000/month. Sensibull is free for Zerodha users and about ₹800 to ₹1,300/month for others. Opstra is about ₹1,300/month, and Quantsapp ₹4,000 to ₹8,000/month. Brokers bundle free strategy builders: Dhan Options Trader, FYERS Strategy Builder and Kite's option chain. Historical options backtesting is weak across the analytics tools. Sensibull has none, Opstra has EOD only, and the dedicated options backtesters are AlgoTest and similar tools.

### Cited Findings
- **Sensibull** features: advanced option chain (Greeks, IV, PCR, probability of profit), OI charts, multi-strike straddle and strangle charts, options screener, strategy builder and wizard, "EasyOptions" limited-risk suggestions, basket orders and virtual (practice) trades. It is free for Zerodha users and works with AngelOne, Upstox, ICICI Direct and 5paisa. Strike lists Pro at ₹1,300/month standard, with a yearly promo of ₹392/month. — [Strike review (updated 28 Apr 2026)](https://www.strike.money/reviews/sensibull)
- Sensibull pricing conflict: the 5paisa help desk lists Pro at ₹800/month + 18% GST (₹3,840 + GST for 6 months), Lite at ₹590 + GST, and ₹20 per-trade brokerage on all plans. OneTradeJournal saw ₹800/month and ₹640/month on Sensibull's homepage. Zerodha users have had free access since 24 July 2023. — [5paisa help](https://forum.5paisa.com/portal/en/kb/articles/what-are-the-subscription-and-brokerage-charges-for-sensibull); [OneTradeJournal (14 Oct 2026)](https://onetradejournal.com/platforms/options-analytics-tools-compared); [Sensibull FAQ](https://sensibull.freshdesk.com/support/solutions/articles/43000586718-what-are-the-charges-of-sensibull-)
- Sensibull has no historical backtesting, per a help article modified 1 Jan 2024. — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared)
- Sensibull ratings: Google Play 4.1 (about 41.4K reviews), App Store 4.8 (about 12K), MouthShut about 2.25. Complaints: strategy analytics and predicted P&L differ from actual outcomes, slow or delayed charts, EasyOptions suggestions underperform in choppy markets, lag when switching tabs, cluttered mobile charts, and email-only support. — [Strike review](https://www.strike.money/reviews/sensibull)
- **Opstra (Definedge)**: the public site is ₹1,300/month + GST, ₹6,000 for 6 months + GST, or ₹11,000/yr + GST (₹12,980). It has a strategy builder, a free chain and dashboard with 15-minute updates, EOD IV and EOD options backtesting. The Definedge-linked terminal is ₹799/month or ₹7,999/yr for Definedge demat clients only. — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared); [OptionX vs Opstra](https://optionx.trade/blogs/optionx-vs-opstra)
- **Quantsapp**: PRO is ₹4,000/month or ₹19,999/yr, and PRO+ ₹8,000/month or ₹39,999/yr, taxes included. Strategy Architect and the option chain are free. IV, OI, backtesting and "specialised analytics" are paid. Live data is advertised on all plans. — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared)
- Reviewers say Quantsapp's site "feels more like a course provider than an analytics platform" and that the cost adds up. — [Fintrakk](https://app.fintrakk.com/article/is-quantsapp-options-analytics-platform-free-to-use)
- **Dhan Options Trader**: ₹0 for Dhan users. Strategy builder with payoff lines, IV adjustment, strategy Greeks and saved comparisons. Dhan-only, with no established backtesting. — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared)
- **Kite native option chain**: OI, IV measures, Greeks, basket orders, margin and position tracking, with a link out to Sensibull. The basket is not a verified payoff builder. — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared)
- **FYERS Strategy Builder**: the Oct 2026 upgrade simplified leg editing and added separate Summary, Payoff, P&L and Greeks views plus a pre-execution fund check. Since Apr 2026, executed strategies auto-save to Strategy History, and users can "edit from positions payoff". FYERS also has "Smart Script" for no-code custom indicators. — [FYERS Product Recap Apr 2026](https://fyers.in/community/t/fyers-product-recap-april-2026/12280); [FYERS what's new](https://fyers.in/whats-new/new-indicators-on-fyers-charts)
- **Trendlyne PRO PLUS** adds "SmartOptions" for F&O at ₹2,000/month or ₹11,900/yr. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)

### Inferences
- Live option chains, payoff and Greeks are commoditised: free from Dhan, FYERS, Kite and Sensibull for Zerodha users. Paid value has moved to historical IV and OI analytics and to options backtesting with realistic fills.
- Tick-level or minute-level historical options backtesting that combines analytics and execution in one place is thin. Sensibull has none, Opstra has EOD, Quantsapp's resolution is unverified, and AlgoTest has it but is a separate product.

### Gaps
- I could not retrieve Sensibull's official current plan page. The ₹800 vs ₹1,300 figures conflict.
- Quantsapp's backtest data resolution and depth were not established.
- I found no independent accuracy test of any tool's "probability of profit" or margin calculator.

## 5. Signal and advisory products for Indian retail: presentation, regulation, claimed vs verified accuracy

### Takeaway
Since the Dec 2024 RA amendments, trading calls, stop-loss targets and model portfolios count as regulated "research services". They need SEBI RA registration and a fee capped at ₹1.51 lakh/yr per family. Apps present each call as entry, target, stop-loss and horizon. Accuracy claims (70% to 80%+ "hit rates") are self-reported. SEBI's PaRRVA verification system (live since 4 May 2026, run by CARE Ratings with NSE as data centre) is the first route to verified track records. After May 2028 only PaRRVA-verified performance may be communicated.

### Cited Findings
**Regulation**
- RA Regulation amendments notified on 16 Dec 2024:
  - Fee cap of ₹1.51 lakh/yr for individual and HUF clients, applied per family and effective 8 Jan 2025.
  - Advance fees limited to one quarter.
  - Cash payments prohibited.
  - Conflicts of interest must be disclosed.
  - Guaranteed-return schemes prohibited.
  - Research scope explicitly includes "giving stop loss targets" and "providing trading calls".
  - Model portfolios need research reports and PaRRVA-validated performance.
  
  — [AZB & Partners](https://www.azbpartners.com/bank/overhaul-of-the-regulatory-framework-for-investment-advisers-and-research-analysts/); [Taxmann: RA fee cap](https://www.taxmann.com/post/blog/sebi-guidance-on-ra-fee-cap-for-individual-and-huf-clients); [Mondaq](https://www.mondaq.com/india/securities/1574012/navigating-the-updated-regulatory-framework-for-investment-advisers-and-research-analysts)
- PaRRVA (Past Risk and Return Verification Agency):
  - SEBI's 29 Apr 2026 circular operationalised it, with CARE Ratings as the agency, NSE as the data centre and services from 4 May 2026.
  - IAs and RAs wanting to communicate past performance had to enrol by 3 Aug 2026, later extended to 3 Sept 2026.
  - After May 2028, only PaRRVA-verified risk and return metrics may be communicated.
  - Before PaRRVA, CA- or CMA-certified data was allowed only on specific client request.
  - Unverified data must carry a disclaimer.
  
  — [SEBI circular PDF (Apr 2026)](https://www.sebi.gov.in/sebi_data/attachdocs/apr-2026/1777473564120.pdf); [Business Standard (29 Apr 2026)](https://www.business-standard.com/markets/news/sebi-parrva-framework-performance-verification-deadlines-126042901492_1.html); [Outlook Money: extension](https://www.outlookmoney.com/invest/sebi-extends-parrva-enrolment-date-for-investment-advisors-research-analysts); [NISM blog](https://www.nism.ac.in/blog/sebi-parrva-how-it-disrupts-mis-selling)
- Finfluencer rules: in force from 29 Aug 2024 and clarified by a 29 Jan 2025 circular. Registered entities cannot associate with unregistered finfluencers for compensation. Educators may use only price data at least 3 months old and may not make performance claims or give advice. — [Business Standard](https://www.business-standard.com/markets/news/sebi-finfluencer-circular-live-stock-data-market-education-rules-125013000571_1.html); [Business Today](https://businesstoday.in/markets/stocks/story/sebis-clampdown-on-finfluencers-cannot-use-live-stock-market-data-in-educational-content-462704-2025-01-31)
- SEBI treats buy, sell or hold recommendations sent via Telegram, WhatsApp, SMS or email as "research reports" needing disclosures. RAs should avoid superlatives such as "best advisor" and guaranteed-profit claims. This comes from a secondary summary by a broker. — [Sahi: Telegram tips vs SEBI-registered research](https://www.sahi.com/blogs/telegram-stock-tips-vs-sebi-registered-research-india)

**Enforcement in 2026**
- May 2026: an interim order barred 7 people in an alleged ₹20.25 crore social-media pump-and-dump in SME stocks run by a family of unregistered "RAs". — [LiveLaw](https://www.livelawbiz.com/securities-law/sebi/sebi-impounds-2025-crore-bars-7-in-alleged-social-media-stock-manipulation-scheme-535429); [Free Press Journal](https://www.freepressjournal.in/business/sebi-bans-7-individuals-in-20-crore-stock-manipulation-case-linked-to-social-media-pump-and-dump-scheme)
- April 2026: orders against paid Telegram channels giving unregistered buy/sell/hold calls. — [SEBI order (30 Apr 2026) mirror](https://rhnvrm.github.io/stock-market-circulars/circulars/sebi/2026/sebi-2026-04-30-1c57bcaedfe3bf77-order-in-the-matter-of-unregistered-investment-advisor-research-analyst-activiti/)
- July 2026: ₹20 lakh fine on 3 people for coordinated Telegram buy calls in Akash Infra-Projects. — [Moneylife](https://www.moneylife.in/article/fssai-bans-folineuro-syrup-stops-sale-of-neuherbs-true-vitamin-orders-recall-of-wonderland-raisins/article/akash-infraprojects-stock-manipulation-sebi-slaps-20-lakh-fine-on-3-for-running-fraudulent-scheme-on-telegram/81200.html)

**How products present calls, and claimed accuracy**
- Univest (SEBI RA INH000013776) presents each idea with entry price, target and stop-loss. Its App Store listing claims "Trusted by 50 lakh+ investors". — [Univest App Store](https://apps.apple.com/in/app/id6443753518)
- Liquide (SEBI RA INH000009816) markets a "70% Hit Rate… Checked by a Chartered Accountant" on its BTST and options landing pages. The audit scope and method are not published. — [Liquide BTST page](https://liquide.life/landing/btst-1); [Liquide options page](https://liquide.life/landing/options-1)
- Multyfi's app listing claims "over 80% accuracy" with no methodology. — [App Store listing](https://apps.apple.com/ly/app/multyfi-app/id6748902495)
- Swastika "Sarthi" advertises transparent performance tracking with a "Past Calls" section. — [Swastika Sarthi](https://www.swastika.co.in/sarthi)
- Bundled advisory: StockEdge Club (₹2,499/month) adds SEBI-registered research ideas. Moneycontrol Super PRO (₹499/month coupon) adds trading calls and AI WhatsApp alerts. MarketsMojo MojoOne and Value Research Stock Advisor sell recommendation services at about ₹10k/yr. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india)
- AlgoTest's "RA Algos" marketplace sells strategies from SEBI-registered RAs. — [AlgoTest pricing blog](https://algotest.in/blog/algo-trading-software-price-in-india/)

**Verified outcomes (context for accuracy claims)**
- SEBI's July 2025 study found 91% of individual equity-F&O traders lost money in FY25. Net losses were about ₹1.06 lakh crore (later revised to about ₹1.12 lakh crore), up 41% from ₹74,812 crore in FY24. Unique F&O participants fell 20%. — [Business Standard](https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html); [Business Standard (participation)](https://www.business-standard.com/markets/news/individual-investors-shrink-20-percent-fo-segment-125070800801_1.html)
- A follow-up SEBI study reported FY26 aggregate individual losses of about ₹91,685 crore, with 87.7% of individual traders still loss-making. — [Finnovate (23 Sept 2026)](https://www.finnovate.in/learn/blog/sebi-fno-trader-losses-fy26-individual-derivatives)

### Inferences
- Every hit-rate figure found (70%, 80%+) is marketing. None is PaRRVA-verified or published with the definition used, such as target-before-stop versus any profitable exit, or the full closed-call list.
- PaRRVA plus the May 2028 cutoff will force RAs toward verified metrics. A platform that natively produces PaRRVA-compatible, auditable call logs (timestamped entry, target, stop-loss and exit) could serve RAs as a B2B customer and retail users as a trust signal.
- SEBI's own loss statistics (about 88% to 91% of F&O traders losing) contrast sharply with 70% to 80% claimed hit rates. Honest stats such as expectancy and net-of-cost P&L, not hit rate, are an unoccupied positioning.

### Gaps
- I found no independent audit of any Indian signal provider's accuracy.
- I did not find the exact RA disclosure format SEBI mandates for individual trading calls (required fields, risk ratings) in the primary regulation text.
- I found no data on how many RAs had enrolled in PaRRVA by the 3 Sept 2026 deadline.

## 6. Common user complaints and unmet needs

### Takeaway
Recurring complaints: paywalled real-time data and features (TradingView, Chartink), broker lock-in (Streak, Dhan, FYERS tools), weak or absent backtesting in analytics tools, backtests that ignore Indian costs and survivorship, unverifiable signal claims, email-only support, no-refund billing, and the need to stitch together 3 to 4 tools. The clearest gaps are: (a) one integrated workspace (charts, scans, options, backtest, execution) across brokers; (b) cost- and tax-realistic, survivorship-free backtests covering equities and F&O; (c) verified, honest strategy and signal statistics.

### Cited Findings
- **Fragmentation**: Indian users typically combine Chartink or BottomStreet for scans, TradingView for charts and AlgoTest for backtests. No single app covers charting, scanning and backtesting. — [Tradomate: Chartink alternatives](https://tradomate.one/blog/best-chartink-alternatives/); [Strike: 20 trading softwares](https://www.strike.money/stock-market/trading-softwares). Both are vendor blogs.
- **TradingView friction**: free NSE data now delayed 15 minutes; indicator caps (2 on Basic); replay paywall; watermarks; USD billing and forex markup (claimed); lag versus broker terminal; no Zerodha order routing. — [AlgoTest](https://algotest.in/blog/tradingview-charts-showing-delayed-data/); [Neostox](https://blog.neostox.com/charting/charting-platform-friction-indian-traders); [TradingQnA](https://tradingqna.com/t/zerodhas-integration-with-tradingview/177136)
- **Chartink**: delayed free data, no app, email-only support, billing disputes. — [Strike](https://www.strike.money/reviews/chartink)
- **Sensibull**: predicted versus actual P&L mismatch, slow charts, mobile clutter, no historical backtesting, email-only support. — [Strike](https://www.strike.money/reviews/sensibull); [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared)
- **Streak**: Zerodha lock-in, 5-condition cap, no multi-leg options, 5 live deployments, strategies not portable. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison); [Zerodha Z-Connect comments](https://zerodha.com/z-connect/?p=368853)
- **Tradetron**: learning curve, usage-based cost creep, uneven marketplace quality, regulatory overhang. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- **Backtest realism**:
  - Survivorship bias from testing only today's index members. One source estimates it overstates small-cap annual returns by about 4.94 percentage points. This is a single-source figure.
  - Slippage defaults to zero in many tools. A suggested minimum is 0.05% to 0.1% per trade for large caps, more for mid and small caps.
  - STT has changed repeatedly. Options STT on sale was 0.0625% of premium until 30 Sept 2024, 0.1% until 31 Mar 2026 and 0.15% from 1 Apr 2026. Futures STT is 0.05% from 1 Apr 2026. Using one rate across a long backtest is wrong.
  
  — [Strike: backtest biases](https://www.strike.money/?p=5233); [DEV: backtesting on NSE data](https://dev.to/trademineai/backtesting-trading-strategies-on-nse-data-what-retail-traders-actually-need-to-know-2n8k); [Alice Blue blog](https://aliceblueonline.com/blog/why-backtest-profit-factor-misleads)
- Business Today confirms the 2026 Union Budget STT increase to 0.05% on futures and 0.15% on options premium, effective 1 Apr 2026. — [Business Today (26 Mar 2026)](https://businesstoday.in/markets/stocks/story/explainer-zerodha-ups-trading-fee-others-may-follow-discount-brokers-going-eternal-way-522486-2026-03-26)
- **Broker cost changes**: from 1 Apr 2026 Zerodha charges an extra ₹20 per F&O order (₹40 total) in cash-collateral-shortfall cases tied to SEBI's 50% cash-collateral norm. Zerodha says the standard fee stays ₹20 and most clients are unaffected. Media reported it more broadly. — [Zerodha support](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/40rs-brokerage); [Zerodha clarification](https://zerodha.com/z-connect/general/clatification-on-additional-brokerage-fno-trades); [Inc42](https://inc42.com/buzz/zerodha-raises-fo-charges-to-%E2%82%B940-per-order-for-certain-intraday-trades/)
- Per Intraday Lab, AlgoTest is the only no-code platform reviewed that models STT and slippage in backtests. — [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison)
- **Unverifiable signals**: hit-rate claims of 70% to 80%+ come without methodology (Liquide, Multyfi). PaRRVA only started on 4 May 2026. — [Liquide](https://liquide.life/landing/btst-1); [Multyfi](https://apps.apple.com/ly/app/multyfi-app/id6748902495); [Business Standard](https://www.business-standard.com/markets/news/sebi-parrva-framework-performance-verification-deadlines-126042901492_1.html)
- **Billing and refunds**: no refunds at Chartink, Tickertape, Trendlyne or StockEdge. Tradetron marketplace subscriptions bill until cancelled. — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india); [AlgoTest pricing blog](https://algotest.in/blog/algo-trading-software-price-in-india/)
- **Algo compliance friction**: static IP, daily 2FA, no long-lived refresh tokens and empanelment complicate self-hosted bots and TradingView webhooks. — [FYERS support](https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026); [TradingQnA](https://tradingqna.com/t/tradingview-india-api-ip-whitelisting-is-any-broker-allowing-orders-directly-from-tradingview-platform/192888)

### Inferences (gap list for a developer)
1. **Point-in-time, survivorship-free NSE/BSE universes** (historical index constituents, delisted stocks, corporate-action-adjusted prices) for equity backtests. No retail tool reviewed advertises this.
2. **A dated Indian cost engine**: STT by date and segment, exchange transaction charges, SEBI fee, stamp duty, GST, brokerage per broker, the ₹40 shortfall case, and STCG/LTCG or business-income tax. Only AlgoTest models some costs, and only for options.
3. **Unified equity plus F&O backtesting**: Streak handles equities but is shallow on options, while AlgoTest and Opstra handle options but are weak on equity scanning.
4. **Honest strategy and signal stats**: expectancy, net-of-cost P&L, max drawdown and number of trades, with full trade logs and PaRRVA-style verification, instead of hit rate.
5. **Broker-agnostic, SEBI-compliant execution**: empanelled, static-IP-aware, Algo-ID-tagged, and working with Zerodha, the broker that TradingView cannot trade through.
6. **Cheaper real-time charting** after TradingView's free NSE delay.

### Gaps
- Reddit (r/IndianStreetBets, r/IndiaInvestments, r/StockMarketIndia) threads could not be retrieved directly. Community sentiment here comes from TradingQnA and review aggregators, not Reddit.
- I found no quantified survey of Indian retail tool usage or market share. The Streak and AlgoTest user counts are vendor or third-party claims.

## 7. Pricing table (INR, as of Oct to Nov 2026 where available)

### Takeaway
Broker-bundled tools are free (Streak, Dhan Options Trader, FYERS tools, Sensibull for Zerodha users, Kite Connect Personal). Single-purpose paid tools cluster at ₹400 to ₹1,300/month. Premium options analytics (Quantsapp) and advanced algo tiers (Tradetron Creator) reach ₹4,000 to ₹9,000/month. Many figures conflict between sources, as marked.

### Cited Findings
| Product | Free tier | Paid price (INR) | Notes / source |
|---|---|---|---|
| TradingView | Basic: NSE delayed 15 minutes (since about Sept 2026), 2 indicators, 3 alerts | Essential ₹1,295/month (₹995/month annual); Plus ₹2,595 (₹2,095); Premium ₹5,095 (₹4,195); BSE add-ons about ₹422 (stocks) and ₹176 (F&O)/month | Pre-tax; checked 14 Oct 2026 — [OneTradeJournal](https://onetradejournal.com/platforms/tradingview-plans-india) |
| Chartink | Yes (about 5 minutes delayed, 5-minute+ timeframes) | ₹780 (30 days); ₹2,220 (90 days); ₹8,500 (365 days) | Tax-inclusive, no refund — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india) |
| Screener.in | Yes | Premium ₹4,999/yr | GST incl., 48-hour refund — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india) |
| Trendlyne | Yes | GuruQ ₹390/month or ₹2,990/yr; StratQ ₹9,900/yr; PRO ₹1,500/month or ₹8,900/yr; PRO PLUS ₹2,000/month or ₹11,900/yr | Coupons common, no refund — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india) |
| Tickertape | Yes | Pro ₹399/month; ₹899 for 3 months; ₹2,999/yr | No refund — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india) |
| StockEdge | Yes | Premium ₹399/month (about ₹1,499/yr coupon); Pro ₹1,499/month (₹5,999/yr); Club ₹2,499/month (₹11,994/yr) | No refund — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india) |
| Moneycontrol | Yes | PRO ₹99/month or ₹499/yr; Super PRO ₹499/month or ₹2,499/yr (coupon prices) | +18% GST — [Tapetide](https://tapetide.com/compare/stock-research-subscription-prices-india) |
| Sensibull | Free for Zerodha users; free plan for others | Pro ₹800/month + GST (5paisa help, OneTradeJournal) vs ₹1,300/month (Strike); Lite ₹590 to ₹600/month | Conflicting — [5paisa](https://forum.5paisa.com/portal/en/kb/articles/what-are-the-subscription-and-brokerage-charges-for-sensibull); [Strike](https://www.strike.money/reviews/sensibull) |
| Opstra (Definedge) | Free chain (15-minute updates) | ₹1,300/month + GST; ₹6,000 for 6 months; ₹11,000/yr + GST; Definedge terminal ₹799/month or ₹7,999/yr | — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared) |
| Quantsapp | Strategy Architect and chain free | PRO ₹4,000/month or ₹19,999/yr; PRO+ ₹8,000/month or ₹39,999/yr | Tax incl. — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared) |
| Dhan Options Trader / DhanHQ API | Free for Dhan clients | ₹0 | — [OneTradeJournal](https://onetradejournal.com/platforms/options-analytics-tools-compared); [Intraday Lab](https://intradaylab.com/blog/algo-trading-without-coding-india-platforms-comparison) |
| FYERS API / Automate / Strategy Builder | Free for FYERS clients | Prime plan for higher API limits (price not found) | — [FYERS](https://fyers.in/offerings/algo-trading) |
| Zerodha Streak | Free, unlimited for Zerodha clients since 17 Jan 2024 | n/a (old tiers ₹350 to ₹980/month discontinued) | 5 live / 15 virtual deployments — [Zerodha](https://zerodha.com/z-connect/?p=368853) |
| Kite Connect | Personal: free (no data) | Connect ₹500/month per key (live + historical data) | Oct 2026 credits or waiver for active traders (conflicting) — [Zerodha support](https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/kite-api/articles/what-are-the-charges-for-kite-apis) |
| AlgoTest | 25 backtests/week, unlimited paper trading | Starter ₹499/month (live deployment) | Vendor's own page — [AlgoTest](https://algotest.in/blog/algo-trading-software-price-in-india/) |
| Tradetron | Free: 1 deployable strategy | Retail ₹1,200; Retail+ ₹2,500; Creator ₹5,000; Creator+ ₹9,000/month (FitGap) vs ₹300 to ₹500 entry (Intraday Lab) | Conflicting, marketplace extra — [FitGap](https://us.fitgap.com/products/tradetron-algo-strategy-marketplace) |
| uTrade Algos | 7-day trial | From ₹999/month ("Prarambh") | — [GetApp](https://www.getapp.com/finance-accounting-software/a/utrade-algos) |
| Quantiply | Unknown | Not published ("higher cost") | — [AlgoTest](https://algotest.in/blog/algo-trading-software-price-in-india/) |
| Liquide / Univest / StockEdge Club (advisory) | Partial | StockEdge Club ₹2,499/month; others not retrieved | RA fee cap ₹1.51 lakh/yr per family — [Taxmann](https://www.taxmann.com/post/blog/sebi-guidance-on-ra-fee-cap-for-individual-and-huf-clients) |

### Inferences
- A realistic "full stack" for an active Indian F&O trader costs about ₹2,500 to ₹6,000/month. One example: TradingView Essential (about ₹1,000) + Chartink Premium (₹780) + Sensibull Pro or Opstra (₹800 to ₹1,300) + AlgoTest Starter (₹499) + Kite Connect (₹500). An integrated product priced below that sum has room.
- Free broker bundles set user expectations that option chains, payoff and basic automation should be free. Paid differentiation has to come from data depth, realism and verification.

### Gaps
- Official pricing pages for TradingView India, Chartink, Sensibull, Tradetron, uTrade Algos, Quantiply and FYERS Prime were not retrieved directly. Several prices are third-party snapshots with known conflicts.
- I did not confirm whether prices include 18% GST for every product. Inclusion is marked only where the source stated it.
