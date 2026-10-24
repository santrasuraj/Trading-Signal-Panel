I checked the spec against the code on `platform-v3` (ff20529), the real `data/results/latest.json` from the 09:18 scan, `curves.parquet`, the store's `meta.json`, the NSE caches, the journal and the scaffold. It needs about 30 changes before two engineers can build from it in parallel. Six of them would put wrong numbers or wrong share counts on screen. The corrected contract below compiles under `tsc --strict`, and is also saved at `C:\Users\suraj\AppData\Local\Temp\claude\D--New-folder\8c8a39c7-06d8-4ca7-a5b2-5aeda1a9ef1f\scratchpad\spec-review\api_contract.ts`.

## Required spec changes

### A. Would show wrong numbers, or make frontend and backend disagree

1. **Share counts from the backtest can't be shown to the user.** The simulation compounds: each position is sized as current equity ÷ max positions (`engine.py:226`). So `positions[].qty` and the planned B1 `qty`/`pnl` are in a portfolio that is now about 11× the starting capital. Example: momentum holds CUPID ×5026 ≈ ₹16 lakh on ₹5 lakh capital. Section 1.3.2's fix ("SELL qty = model qty") is therefore wrong.
   - SELL qty = what the user holds; otherwise `floor(alloc × weight_pct / price)`.
   - Add `Order.qty_basis` and make `qty` nullable.
   - `ModelPosition` shows `weight_pct` instead of qty. Weight = qty × last ÷ (capital × last curve value).
   - Drop `qty`/`pnl` from `TradeRow`.
2. **`recent_trades` fields are misnamed in the spec.** The real fields are `{symbol, entry, exit, ret_pct, days, reason}`. There are no prices, qty or pnl. Map `entry`→`entry_date` and `exit`→`exit_date`, and make the prices nullable.
3. **Window CAGR is null by construction.** `_curve_stats` returns null CAGR under 0.5 years, so `m3.cagr_pct` is always null. All window columns must use `return_pct`.
4. **Missing benchmarks are encoded as `{}`, not null.** Example: `factor_benchmark: {}` for event strategies. Strategy-level `benchmark` is `''`. The API must normalise both to null; `benchmark_name` becomes `factor_benchmark_name`.
5. **Optional keys are left out, not set to null.**
   - `results_in_days` is missing whenever `results_on` is null.
   - Holdings rows with level `unknown` carry only `symbol`, `level` and `alerts`.
   - `results_in_days` is counted from the scan day, so the API must recompute it against today's IST date.
6. **Mixed units and formats need converting.**
   - `status.json.progress` is a 0–1 fraction, which breaks the percent-only rule. Rename to `progress_pct` (×100).
   - `status.json.started` is epoch seconds, and the lock's `started` is `'HH:MM:SS'` with no date. Both become ISO datetimes.
   - `meta.failed` is `{sym: {count, last_try}}`, not `Record<string, string>`.
7. **Intraday P3 contract doesn't match the code that exists.** An intraday engine already sits untracked in the worktree (`scanner/intraday/`). It uses 5-minute bars, writes `data/results/intraday.json`, uses different trade fields (`entry_time`, `exit`, `ret_pct`…), and squares off at 15:00 (F&O) and 15:15 (others), not the spec's 15:05/15:20. The spec also says 1-minute bars and a different storage path. Replace endpoints 40–45 with one `GET /api/intraday` that wraps `intraday.json`. Square-off times and the SEBI facts come from that file as text; don't hard-code SEBI numbers as literal types.
8. **Paper:** call the existing `paper.paper_report()` rather than `build_report` plus manual mapping. Its summary has no `key` (inject it) and has `comparison` and `kind`, which the spec lacks. Equity arrives as `[[date, value]]` pairs and becomes columnar.
9. **Duplicated fields** (spec has two copies, which can drift):
   - Remove `StrategyDetail.windows`; it's built from `metrics`.
   - Remove the top-level `StrategyDetail.timing`; it lives in `strategy.timing`.
   - Remove `AsOf.provisional`; it is the same as `live`.
10. **`ChartBars.t: (ISODate | number)[]` is ambiguous.** The daily chart is `ISODate[]` only. Weekly bars are stamped with the last trading date of the week, not the W-FRI label, so markers line up.
11. **Indicator names don't match `add_indicators`.** It outputs `rsi`, not `rsi14`, and has no Bollinger, `macd_hist` or VWAP. Those are computed in `chart_data.py`. Drop `vwap`, `ema9`, `atr14` and the `5m`/`15m` timeframes from the daily chart.
12. **Alert gaps:**
    - The wireframe's "STLTECH (#1 momentum) reports today" alert comes from no rule. Add a `results` rule covering held, model, ranked and order symbols reporting within `warn_days`.
    - Holdings level `ok` has no severity mapping; map it to info.

### B. Data and process hazards found in the real files

13. **The worktree's `data/` is a symlink to the main checkout's `data/`.** It is shared with the main checkout, which is currently on `pit-universe`, with master, and with the other two sessions. The 60 saved scans already mix schemas: 3, 5, 6 and 13 strategies; only the 09:18 one has `indices`. Any scan from the main checkout (scheduled tasks, `2_scan.bat`, Streamlit) overwrites `latest.json` in the old schema.
    - Add `AsOf.legacy_producer` plus a global banner.
    - "Since last scan" must diff only keys present in both scans.
    - Record a producer/commit field in `latest.json`.
14. **`holdings.csv`, `config.yaml` and `.env` are not shared.** `settings.ROOT` is the checkout, so the platform edits the worktree copy while main-checkout scans read their own copy. Document this; holdings health is only correct for scans started by the platform until the branch merges.
15. **`_save` write order and atomicity are unsafe.**
    - `latest.json` is written first and `curves.parquet` last; the curves file is written in place, not atomically.
    - The UI invalidates on a new `scan_id` and can cache old or truncated curves forever (`staleTime: Infinity`).
    - **Fix (B9, new):** write curves and the trades/screener artifacts first via tmp + `store._replace` (the Windows-safe retry already used by the store), and `latest.json` last as the commit marker.
16. **No GET handler may call scanner functions that hit the network.** `get_universe`, `upcoming_results`, `trading_holidays` and `index_history` all fetch from NSE when their cache is stale. `/api/status` is polled every 1–10 s. The API reads `universe_*.csv`, `events_*.json`, `holidays_<year>.json` (the `CM` key) and `index_history.parquet` directly. `NSE_UNAVAILABLE` is dropped.
17. **B6 is already done.** The merge (ff20529, 09:24) came after the 09:18 scan. Platform `daily.py` already emits `min_position`, `paper{}`, `rules{stop_pct, target_pct, trail_pct, sizing, risk_pct}` and `te_n500_pct`; they appear after the next scan. `pit.py` is not on master; it is on the `pit-universe` branch, so B7 depends on that session.
18. **B5 should cover the full rules, not just `params`.** Add `rebalance`, `top_n`, `keep_rank`, `stop_atr`, `max_hold`, `use_regime` and `regime_action` from the strategy object, plus the raw config. That way the API never re-reads `build_strategies` against a config edited after the scan. Add `rules.source` and `config_changed_since_scan`.
19. **Breadth history must match the snapshot.** Use the same symbol list and ETF exclusion as `daily.py`, or the chart's last point won't equal `market.breadth_50`.

### C. Performance traps

20. **Time series as arrays of `{t, v}` objects are too big.** 1,774 points × 5 series ≈ 280 KB, against the spec's own 120 KB target; breadth with 7 fields × 2,042 points is worse. Use columnar `TimeSeries` everywhere.
21. **Make B2 the screener's only source and drop the fallback** (501 until the next scan). Computing the full set of whole-market indicators from the store inside the API means seconds of CPU and hundreds of MB of RAM, and the p95 budget is impossible on a cold start.
22. **Sparklines: allow up to 500 symbols per call, not 100.** The screener has about 500 rows; one call loads them all.
23. **Don't open the store with memory-mapping on Windows.** It would lock old store folders so `rmtree` fails silently.
24. **`/api/status` must be file-stat and cache reads only.** No Fyers calls (`get_fyers` runs a profile check) and no NSE calls.
25. **B4 (testing rejected strategies) adds simulation time to every scan.** Scans already went from ~12 s with 3 strategies to 122 s with 13. Cache B4 by signature and skip the timing range for rejected strategies.

### D. Over-engineering to remove

26. **Endpoints to remove:**
    - `/api/curves`: no page uses it.
    - `/api/rankings/{key}`: same data as the strategy detail.
    - `/api/market/clock` and `/api/scan/status`: already in `/api/status`.
    - The `lifecycle` query parameter: the response already splits active and rejected.
    - `HoldingsPutRequest.mode`: it has only one value.
    - The 'callback' Fyers login mode: move it to P2.
    - The typed B8 validation block: stays `null` until B8 exists.
27. **Remove `overview.sectors_top`/`sectors_bottom`:** no Overview widget uses them. Add the missing `index_tiles` (with a 63-point sparkline from the index history; India VIX is in it).
28. **`signals_final` logic** is replaced by `clock.last_completed_day` plus `AsOf.stale`.

### E. Wrong statements in the spec

29. **Wrong facts:**
    - The 09:18 scan took **122.1 s**, not 11.6 s; 11.6 s was a 3-strategy master scan at 08:34.
    - `stocks` is **483** (including the 5 ETFs), not 478.
    - There are 133 corporate actions, not 125.
    - The strategy-detail yearly wireframe values are from another scan; real momentum: 11.5 / 93.6 / 97.7 / −1.4 / 103.8 / 38.7 / −16.3 / 13.5.
    - Momentum volatility is 23.5, not 23.6.
    - index_trend max drawdown is −14.3, not −14.4.
30. **Wrong dependency claims:**
    - The scaffold has lightweight-charts **4.2.1**, not 5.2.1.
    - react-table is 8.20.5, not 8.21.3.
    - `package.json` uses caret ranges; pin them exactly.
    - cmdk and the fontsource packages are not installed; `index.html` still loads Google Fonts.
    - `ruamel.yaml` and `httpx` are **not** in `.venv`.
    - Keep React **19.3.1** from the scaffold: downgrading is churn and nothing in the request requires 18.
31. **SPA fallback path traversal.** `main.py` serves `DIST / path` with no check. Resolve the path and require `is_relative_to(DIST)`.

## Final API contract

```ts
// Quant Desk v3 - FINAL API contract (reviewed against platform-v3 @ ff20529 and data/results of 23 Oct 2026 09:18).
// Source of truth at build time = pydantic models in web/api/models; this file is what they must transcribe 1:1.
// Wire rules: snake_case; every declared field always present (unknown = null); NaN/inf -> null;
// percent fields end in _pct or are documented as percent units (12.3 = 12.3%); FRACTIONS ARE NEVER SENT;
// money in rupees; ISODate 'YYYY-MM-DD' (IST trading date); ISODateTime ISO-8601 with +05:30.
// Time series are ALWAYS columnar (TimeSeries), never arrays of {t,v} objects.

// ------------------------------------------------------------------ primitives
export type ISODate = string;
export type ISODateTime = string;
export type Horizon = 'intraday' | 'swing' | 'longterm';
export type StrategyKind = 'rank' | 'event';                       // intraday strategies live under /api/intraday
export type StrategyStatus = 'working' | 'mixed' | 'not-working' | 'unknown';
export type Lifecycle = 'active' | 'disabled' | 'rejected';
export type Evidence = 'STRONG' | 'MODERATE' | 'WEAK' | 'FOLKLORE' | 'EXPERIMENTAL';   // '' in latest.json -> 'EXPERIMENTAL'
export type Tone = 'good' | 'neutral' | 'bad';
export type Side = 'BUY' | 'SELL';
export type AssetUniverse = 'stocks' | 'etfs';
export type ErrorCode = 'NO_SCAN' | 'NOT_FOUND' | 'VALIDATION' | 'SCAN_BUSY' | 'FYERS_NOT_CONFIGURED'
  | 'FYERS_LOGIN_REQUIRED' | 'FYERS_AUTH' | 'FYERS_RATE_LIMIT' | 'FEATURE_UNAVAILABLE'
  | 'CSRF' | 'FORBIDDEN_HOST' | 'INTERNAL';                        // NSE_UNAVAILABLE dropped: no GET handler may call NSE
export type ClientErrorCode = ErrorCode | 'OFFLINE';               // client.ts only

export interface ApiError { error: { code: ErrorCode; message: string; hint: string | null; details: Record<string, unknown> | null } }

/** Columnar series sharing one time axis. v[i] aligns with t[i]. */
export interface TimeSeries {
  t: ISODate[];
  series: { id: string; label: string; role: 'strategy' | 'benchmark' | 'factor' | 'paper'; v: (number | null)[] }[];
}

export interface AsOf {
  scan_id: string;                     // == latest.generated_at (scan START time); changes on every scan incl. re-checks
  generated_at: ISODateTime;
  elapsed_s: number;
  data_date: ISODate;
  live: boolean;                       // today's candle still forming => every order is provisional
  live_source: string | null;
  complete_upto: ISODate | null;
  stale: boolean;                      // data_date < last completed trading day (clock rules below)
  legacy_producer: boolean;            // latest.json written by a checkout without the strategy library
                                       // (no 'indices' key or strategies without 'horizon') -> global banner
  backtest_universe: 'current_list' | 'point_in_time';   // B7; absent -> 'current_list'
  universe_note: string;               // latest.universe, e.g. 'NIFTY500 (cached list)'
  tradable: number;                    // latest.stocks (liquid instruments INCLUDING the 5 ETFs; 483 today)
  capital: number;
  min_position: number;                // latest.min_position ?? config.account.min_position ?? 0
  costs_round_trip_pct: number;
}

// ------------------------------------------------------------------ metrics (mirror engine.evaluate; latest '12m'/'6m'/'3m' -> m12/m6/m3)
export interface PerfStats {           // {} in latest.json (no series) -> null at the parent, never an all-null object
  return_pct: number | null;
  cagr_pct: number | null;             // null when the window is < 0.5 y: ALWAYS null for m3; use return_pct for windows
  max_dd_pct: number | null; sharpe: number | null; vol_pct: number | null;
  after_tax_cagr_pct: number | null;   // present only on full-period strategy + benchmarks
}
export interface TradeStats {
  trades: number; win_rate: number | null; avg_win_pct: number | null; avg_loss_pct: number | null;
  expectancy_pct: number | null; profit_factor: number | null; avg_days: number | null;
}
export interface WindowMetrics extends PerfStats, TradeStats {
  benchmark: PerfStats | null;          // Nifty 50 (store NIFTY50)
  ew_benchmark: PerfStats | null;       // average stock of the same (biased) list
  n500_benchmark: PerfStats | null;     // real Nifty 500
  factor_benchmark: PerfStats | null;   // matching NSE factor index; null for most event strategies
}
export interface FullMetrics extends WindowMetrics {
  exposure_pct: number | null; start: ISODate; end: ISODate; after_tax_return_pct: number | null;
  cagr_range: [number, number] | null; te_n500_pct: number | null; factor_benchmark_name: string | null;
}
export interface StrategyMetrics { full: FullMetrics; m12: WindowMetrics | null; m6: WindowMetrics | null; m3: WindowMetrics | null }

// ------------------------------------------------------------------ 1. system
// GET /api/health -> { ok: true; version: string; uptime_s: number }
export type MarketSession = 'pre_open' | 'open' | 'post_close' | 'closed' | 'holiday' | 'weekend';
export interface MarketClock {
  now: ISODateTime; session: MarketSession; is_trading_day: boolean; holiday_name: string | null;
  next_open: ISODateTime | null;
  last_completed_day: ISODate;          // drives AsOf.stale: today if trading day and now >= 18:00, else previous trading day
  holidays_known: boolean;              // false if data/nse/holidays_<year>.json is missing (clock then ignores holidays)
}
export type ScanState = 'idle' | 'starting' | 'running' | 'done' | 'failed' | 'busy';
export interface ScanStatus {
  state: ScanState; running: boolean;
  progress_pct: number | null;          // status.json 'progress' is a 0..1 fraction -> x100 here
  message: string | null;
  started_at: ISODateTime | null;       // status.json 'started' is epoch seconds; lock 'started' is 'HH:MM:SS' -> both converted
  by: string | null; pid: number | null; update: boolean | null;
  exit_code: number | null;
}
export interface Features {
  paper: boolean;                       // data/journal.sqlite exists and has rows
  pit: boolean;                         // B7 present
  intraday: boolean;                    // data/results/intraday.json exists
  trades_artifact: boolean;             // B1
  screener_artifact: boolean;           // B2
  rejected_tested: boolean;             // B4
  config_edit: boolean;                 // P2
}
export interface Ticker {
  nifty: number | null; nifty_change_pct: number | null;
  nifty500: number | null; nifty500_change_pct: number | null;   // indices.factors 'Nifty 500' (chg_1d is 1-dp in source)
  vix: number | null; vix_change_pct: number | null;
  advances: number; declines: number;
  label: 'Bullish' | 'Mixed' | 'Bearish';
}
export interface AppStatus {               // GET /api/status - polled; MUST be file-stat/cached reads only (no NSE, no Fyers)
  server_version: string;
  latest: AsOf | null;                      // null => onboarding
  scan: ScanStatus;
  fyers: FyersStatus;                       // verify=false variant
  clock: MarketClock;
  features: Features;
  ticker: Ticker | null;
  config_changed_since_scan: boolean;       // config.yaml mtime > generated_at -> "needs re-scan" chip
}

// ------------------------------------------------------------------ 2. overview
export interface MarketSnapshot {
  label: 'Bullish' | 'Mixed' | 'Bearish'; level: Tone; advice: string; regime_up: boolean;
  nifty: number | null; nifty_change_pct: number | null;
  nifty_sma200: number | null; nifty_vs_sma200_pct: number | null;   // B3, else store NIFTY50.rolling(200, min_periods=180)
  nifty500: number | null; nifty500_change_pct: number | null;
  vix: number | null; vix_change_pct: number | null; high_vix: boolean;   // vix >= 20
  breadth_50: number | null; advances: number; declines: number;
}
export interface IndexTile {                 // Overview tiles: 'Nifty 50' | 'Nifty 500' | 'India VIX' | 'Nifty200 Momentum 30'
  name: string; last: number | null; chg_1d_pct: number | null;
  spark: (number | null)[];                  // last 63 closes from data/nse/index_history.parquet (oldest first)
  href: string;                              // '/market/factors'
}
export interface Mover { symbol: string; company: string | null; industry: string | null; price: number | null; change_pct: number | null; vol_ratio: number | null }
export type AlertSeverity = 'danger' | 'warn' | 'info' | 'good';
export interface Alert {
  id: string;                                // `${category}:${symbol ?? ''}:${rule}` (stable across scans; used for dismissal)
  severity: AlertSeverity;
  category: 'holding' | 'order' | 'results' | 'data' | 'login' | 'scan' | 'market' | 'paper' | 'bias';
  title: string; detail: string | null; symbol: string | null; strategy_key: string | null; href: string | null;
}
export interface Change {
  kind: 'status' | 'regime' | 'new_order' | 'position_opened' | 'position_closed';
  text: string; strategy_key: string | null; symbol: string | null;
}
export interface OverviewResponse {
  as_of: AsOf;
  market: MarketSnapshot;
  index_tiles: IndexTile[];
  orders: Order[];                           // all active-lifecycle strategies; client groups by horizon; comparison_only flagged per order
  empty_reasons: Record<Horizon, string | null>;
  alerts: Alert[];                           // sorted danger > warn > info > good
  changes: { since_scan_id: string | null; since_data_date: ISODate | null; items: Change[] };   // [] when no earlier data_date exists
  strategy_pulse: StrategySummary[];         // first 6 active, server order
  movers: { gainers: Mover[]; losers: Mover[]; volume_spikes: Mover[] };   // 5 each
  results_soon: ResultsEvent[];              // <= 7 days AND relevant (held / model / order / ranked top 40)
  paper: PaperSummary[];                     // [] if no journal
}
// GET /api/market/breadth?range=1y|3y|all -> BreadthResponse (columnar; same symbol list + ETF exclusion as daily.py,
//   so the last completed point equals market.breadth_50 when !live)
export interface BreadthResponse {
  source_date: ISODate;                      // last store bar (completed days only; excludes a live candle)
  t: ISODate[];
  breadth_50: (number | null)[]; nifty: (number | null)[]; nifty_sma200: (number | null)[];
  nifty500: (number | null)[]; vix: (number | null)[]; ad_line: (number | null)[];
}

// ------------------------------------------------------------------ 3. strategies
export interface Edges {
  primary: 'ew' | 'nifty';                   // 'nifty' when universe === 'etfs'
  vs_ew_cagr_pct: number | null; vs_n500_cagr_pct: number | null;
  vs_nifty_cagr_pct: number | null; vs_factor_cagr_pct: number | null;
  r12m_vs_n500_pct: number | null; r6m_vs_n500_pct: number | null;   // window return_pct differences (not CAGR)
}
export interface TimingRange {
  base_cagr_pct: number | null; low: number | null; high: number | null;
  consistent: boolean;                       // low <= base <= high (false today for earnings_gap, index_trend, vcp, trend_breakout...)
  method: 'rebalance_offsets' | 'start_offsets';   // rank vs event
}
export interface StrategySummary {
  key: string; name: string; description: string;
  kind: StrategyKind; horizon: Horizon; evidence: Evidence; universe: AssetUniverse; lifecycle: Lifecycle;
  status: StrategyStatus; status_reason: string; rejected_reason: string | null;
  comparison_only: boolean;                  // status === 'not-working' || lifecycle !== 'active'
  headline: {
    cagr_pct: number | null; after_tax_cagr_pct: number | null; max_dd_pct: number | null; sharpe: number | null;
    vol_pct: number | null; win_rate: number | null; trades: number; exposure_pct: number | null; avg_days: number | null;
    ret_12m_pct: number | null; ret_6m_pct: number | null; ret_3m_pct: number | null; n500_12m_pct: number | null;
  };
  edges: Edges;
  timing: TimingRange | null;
  factor_benchmark_name: string | null;      // latest strategy.benchmark '' -> null
  max_positions: number; per_position: number;
  positions: number; orders_buy: number; orders_sell: number;
  rebalance: string | null; next_rebalance: ISODate | null;   // rank only
  uses_regime_filter: boolean; blocked_by_regime: boolean;
  spark: number[];                           // <= 120 evenly sampled points of curves.parquet[key] (growth of 1)
  paper: { return_pct: number | null; days: number; level: Tone } | null;
}
export interface RejectedEntry {             // fallback rows until B4 metrics exist
  key: string; name: string; horizon: Horizon; evidence: Evidence; result_text: string; source: 'catalogue';
}
// GET /api/strategies?horizon=   (no lifecycle param: the response is already split)
export interface StrategyListResponse {
  as_of: AsOf;
  period: { start: ISODate; end: ISODate };
  benchmarks: { nifty50: PerfStats | null; nifty500: PerfStats | null; average_stock: PerfStats | null; survivorship_gap_pct: number | null };
  counts: Record<Horizon, number>;           // active only; intraday = count from intraday.json (0 if absent)
  strategies: StrategySummary[];             // lifecycle 'active', daily.py order
  rejected: StrategySummary[];               // B4 rows (lifecycle rejected/disabled); [] before B4
  rejected_catalogue: RejectedEntry[];       // [] once B4 ships
}
export interface YearlyRow { year: number; partial: boolean; strategy: number | null; nifty500: number | null; average_stock: number | null; nifty50: number | null }
export interface MonthlyRow { year: number; months: (number | null)[]; total: number | null }   // months[0] = Jan; 12 entries
export interface StrategyRules {             // from latest.strategies[i].rules (+ B5 fields); never from a re-read config
  kind: StrategyKind; rebalance: string | null; top_n: number | null; keep_rank: number | null; max_positions: number;
  stop_pct: number | null; stop_atr: number | null; target_pct: number | null; trail_pct: number | null; max_hold: number | null;
  sizing: 'equal' | 'risk'; risk_pct: number | null; use_regime: boolean; regime_action: 'hold' | 'cash' | null;
  params: Record<string, unknown>;           // raw config.yaml strategies.<key> as used by the scan (B5)
  plain_rules: string[];                     // services/catalog.py
  source: 'scan' | 'config';                 // 'config' = B5 missing, read from build_strategies(current cfg) -> may differ from the scan
}
export interface EvidenceCard {
  grade: Evidence; catalogue_id: string | null; summary: string; what_to_expect: string;
  sources: { title: string; url: string | null }[]; failure_modes: string[];
  validation: null;                          // B8 (P2): typed when it exists, not before
}
export interface ModelPosition {
  symbol: string; company: string | null; industry: string | null;
  entry_date: ISODate; entry_price: number; last_price: number | null; ret_pct: number | null;
  stop: number | null; days: number;
  weight_pct: number | null;                 // qty*last / (capital * curves[key].last) * 100  - the backtest compounds,
                                             // so its share count is NOT a share count for the user and is not exposed
  results_on: ISODate | null; results_in_days: number | null;   // recomputed vs IST today, not scan day
}
export interface RankingRow {
  rank: number; symbol: string; company: string | null; industry: string | null; score: number | null; price: number | null;
  ret_6m_pct: number | null; ret_12m_pct: number | null; rs: number | null; in_portfolio: boolean;
  results_on: ISODate | null; results_in_days: number | null;
}
export interface TradeRow {                  // B1 trades.parquet, else latest.recent_trades (entry/exit -> entry_date/exit_date)
  symbol: string; entry_date: ISODate; exit_date: ISODate;
  entry_price: number | null; exit_price: number | null;   // null when source === 'recent_only'
  ret_pct: number | null; days: number; reason: string;
  // qty / pnl deliberately omitted: the backtest compounds (11x by 2026), its rupee P&L is meaningless at user capital
}
// GET /api/strategies/{key}
export interface StrategyDetail {
  as_of: AsOf;
  strategy: StrategySummary;                 // carries timing; there is no second copy
  metrics: StrategyMetrics;                  // the windows table is built client-side from this (no separate 'windows')
  yearly: YearlyRow[];                       // calendar years from curves.parquet for the strategy and the benchmarks: year-end / previous year-end - 1 (first year over the first value); latest.yearly only as a fallback (daily.py uses the same formula)
  monthly: MonthlyRow[];
  rules: StrategyRules;
  evidence: EvidenceCard;
  positions: ModelPosition[];
  orders: Order[];                           // identical rows to /api/signals for the same allocations
  ranking: RankingRow[];                     // [] for event strategies
  recent_trades: TradeRow[];                 // last 25
  trades_available: boolean;
  regime_note: string | null;
  paper: PaperSummary | null;
}
// GET /api/strategies/{key}/curve?range=1y|3y|all -> CurveResponse (columnar, rebased to 1.0 at range start;
//   ₹ view = value * capital client-side; series: key, 'NIFTY 500', 'Average stock', 'NIFTY 50', factor if available)
export interface CurveResponse {
  as_of: AsOf; key: string; range: '1y' | '3y' | 'all';
  curve: TimeSeries;
  drawdown: TimeSeries;                      // ids: key, 'NIFTY 500'; percent (<= 0)
  capital: number;
}
// GET /api/strategies/{key}/trades?page=&page_size=50&outcome=all|win|loss&reason=&symbol=&sort=-exit_date
export interface TradesPage {
  as_of: AsOf; key: string; source: 'artifact' | 'recent_only';
  total: number; page: number; page_size: number; rows: TradeRow[];
  stats: TradeStats;                         // over the filtered set (profit_factor from ret_pct when source='recent_only')
  histogram: { bin_lo: number; bin_hi: number; count: number }[];   // 2% bins, clamped to [-30, +100]
  reasons: { reason: string; count: number; avg_ret_pct: number | null }[];
}

// ------------------------------------------------------------------ 4. signals and sizing
export interface Order {
  strategy_key: string; strategy_name: string; strategy_status: StrategyStatus; horizon: Horizon;
  comparison_only: boolean;
  action: Side; symbol: string; company: string | null; industry: string | null; reason: string;
  price: number | null;                      // price used for sizing (scan close / live)
  qty: number | null;                        // see qty_basis; null = cannot size (no price, or SELL you don't hold and no weight)
  qty_basis: 'sized' | 'your_holding' | 'model_weight';
                                             // BUY: 'sized'. SELL: 'your_holding' if holdings.csv has it,
                                             // else 'model_weight' = floor(alloc * weight_pct/100 / price)
  amount: number | null;                     // qty * price
  stop: number | null; stop_distance_pct: number | null;   // (stop/price - 1)*100, negative
  risk_amount: number | null;                // BUY only: qty * (price - stop)
  results_on: ISODate | null; results_in_days: number | null; results_warning: boolean;
  provisional: boolean;
  below_min_position: boolean;               // BUY amount < min_position (the backtest would skip it)
  you_hold_qty: number | null;
}
export interface Allocation { strategy_key: string; pct: number; capital: number }
export interface SignalGroup {
  strategy: StrategySummary;
  sizing: { capital: number; per_position: number; max_positions: number; sizing: 'equal' | 'risk'; risk_pct: number | null };
  orders: Order[];
  empty_reason: string | null;
}
// GET /api/signals?horizon=&allocations=momentum:60,earnings_gap:40   (debounce what-if drags >= 250 ms)
export interface SignalsResponse {
  as_of: AsOf;
  capital: number; min_position: number;
  allocations: Allocation[];
  allocation_source: 'config' | 'query' | 'none';
  allocation_warning: string | null;
  sized_like_scan: boolean;                  // true when allocation_source==='none' (rows equal latest.json / Telegram)
  regime: { regime_up: boolean; note: string | null };
  groups: SignalGroup[];                     // non-comparison groups first
  totals: { buy_count: number; sell_count: number; buy_amount: number; sell_amount: number | null; risk_amount: number; results_warnings: number };
}
// Sizing (services/sizing.py; must equal daily.sized when there are no allocations):
//   alloc = allocations ? capital*pct/100 : capital; per_pos = alloc / max_positions; qty = floor(per_pos / price)
//   risk sizing (event, sizing=='risk', stop < price): qty = min(floor(alloc*risk_pct/100/(price-stop)), floor(2*per_pos/price))

// ------------------------------------------------------------------ 5. screener, symbols, sparklines
export interface ScreenerRow {
  symbol: string; company: string | null; industry: string | null; price: number | null; change_pct: number | null;
  ret_1w_pct: number | null; ret_1m_pct: number | null; ret_3m_pct: number | null; ret_6m_pct: number | null; ret_12m_pct: number | null;
  rs: number | null; momentum_score: number | null; momentum_rank: number | null; vol_ann_pct: number | null;
  pct_from_52w_high: number | null; above_sma50: boolean | null; above_sma200: boolean | null; sma50_above_sma200: boolean | null;
  rsi14: number | null; vol_ratio: number | null; turnover_cr: number | null; atr_pct: number | null; deliv_pct: number | null;
  results_on: ISODate | null; in_models: string[]; you_hold: boolean;
}
// GET /api/screener?preset=momentum|rs|near_high|low_vol|volume|uptrend|all&industry=&min_turnover_cr=&in_models=&results_within=&sort=
//   B2 artifact only. Missing -> 501 FEATURE_UNAVAILABLE details.feature='screener' ("appears after the next scan").
export interface ScreenerResponse { as_of: AsOf; source_date: ISODate; preset: string; total: number; rows: ScreenerRow[] }
export interface SymbolInfo { symbol: string; company: string | null; industry: string | null; kind: 'stock' | 'etf' | 'index'; in_universe: boolean }
// GET /api/symbols -> { as_of: AsOf | null; symbols: SymbolInfo[] }   (universe csv read directly; never get_universe())
// GET /api/sparklines?symbols=A,B,...&days=60   (max 500 symbols, one call per screener load)
export interface SparklinesResponse { source_date: ISODate; days: number; series: Record<string, (number | null)[]> }   // closes rounded to 2 dp

// ------------------------------------------------------------------ 6. chart and stock
export type IndicatorId = 'sma20' | 'sma50' | 'sma200' | 'ema21' | 'bb_upper' | 'bb_mid' | 'bb_lower'
  | 'rsi14' | 'macd' | 'macd_signal' | 'macd_hist' | 'vol_avg20';
// GET /api/chart/{symbol}?tf=1d|1w&range=3m|6m|1y|2y|5y|max&indicators=sma20,sma50,sma200,rsi14   (daily store only; intraday has its own endpoint later)
export interface ChartResponse {
  symbol: string; company: string | null; industry: string | null; kind: 'stock' | 'etf' | 'index';
  tf: '1d' | '1w'; range: string; adjusted: true; source_date: ISODate;
  bars: { t: ISODate[]; o: number[]; h: number[]; l: number[]; c: number[]; v: number[] };
     // NaN-close rows dropped; 1w: t = LAST TRADING DATE of the week (not the W-FRI label), O first/H max/L min/C last/V sum
     // index symbols (NIFTY50, INDIAVIX, NIFTY500): v = 0
  indicators: Partial<Record<IndicatorId, (number | null)[]>>;   // computed on full history, then sliced; aligned to bars.t
  markers: ChartMarker[];
  price_lines: PriceLine[];
  strategies_available: { key: string; name: string; trades: number }[];   // [] without B1
  results_on: ISODate | null;
  past_results: ISODate[];                   // from data/nse/results_*.json within range
}
export interface ChartMarker {
  t: ISODate; position: 'aboveBar' | 'belowBar' | 'inBar'; shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  kind: 'entry' | 'exit' | 'open_entry' | 'pending_order' | 'corporate_action' | 'results';
  tone: 'profit' | 'loss' | 'neutral' | 'warn'; text: string; detail: string | null; strategy_key: string | null;
}
export interface PriceLine {
  price: number; label: string; strategy_key: string | null;
  kind: 'model_entry' | 'model_stop' | 'order_stop' | 'your_buy' | 'your_stop' | 'your_target' | 'high_52w' | 'low_52w';
}
// GET /api/stock/{symbol}
export interface StockSnapshot {
  as_of: AsOf | null; symbol: string; company: string | null; industry: string | null; kind: 'stock' | 'etf' | 'index';
  price: number | null; change_pct: number | null; data_date: ISODate | null;
  high_52w: number | null; low_52w: number | null; pct_from_52w_high: number | null;   // same definition as the screener (includes today)
  ret_1m_pct: number | null; ret_3m_pct: number | null; ret_6m_pct: number | null; ret_12m_pct: number | null;
  rs: number | null; momentum_rank: number | null; sma50: number | null; sma200: number | null;
  vol_ratio: number | null; turnover_cr: number | null; deliv_pct: number | null; results_on: ISODate | null;
  strategies: { key: string; name: string; status: StrategyStatus; role: 'holding' | 'order' | 'ranked'; detail: string }[];
  your_holding: HoldingRow | null;
  corporate_actions: { date: ISODate; factor: number; reason: string }[];
}

// ------------------------------------------------------------------ 7. holdings (holdings.csv is per CHECKOUT: ROOT/holdings.csv)
export interface HoldingInput { symbol: string; qty: number | null; buy_price: number | null; buy_date: ISODate | null; stop_loss_pct: number | null; target_pct: number | null }
export type HoldingLevel = 'ok' | 'good' | 'watch' | 'danger' | 'unknown';
export interface HoldingRow {
  symbol: string; company: string | null; industry: string | null; qty: number | null; buy_price: number | null; price: number | null;
  change_pct: number | null; pnl_pct: number | null; pnl_amount: number | null;
  stop_price: number | null; target_price: number | null; momentum_rank: number | null; rs: number | null;
  results_on: ISODate | null; level: HoldingLevel; alerts: string[];        // 'unknown' rows carry only symbol/level/alerts in latest.json
  value: number | null; day_pnl: number | null; weight_pct: number | null; in_models: string[];
}
// GET /api/holdings
export interface HoldingsResponse {
  as_of: AsOf | null; rows: HoldingRow[]; inputs: HoldingInput[];
  health_stale: boolean;                     // holdings.csv mtime > generated_at, or symbol sets differ
  totals: { count: number; invested: number | null; value: number | null; pnl: number | null; pnl_pct: number | null; day_pnl: number | null; danger: number; watch: number };
  by_industry: { industry: string; weight_pct: number }[];
  defaults: { stop_loss_pct: number; target_pct: number };
}
// PUT /api/holdings  body { rows: HoldingInput[] }  (full replacement; header X-Quant-Desk: 1)
export interface HoldingsPutResponse { saved: number; rejected: { index: number; symbol: string; reason: string }[]; unknown_symbols: string[] }
// POST /api/holdings/import/fyers  (preview only) -> { rows: HoldingInput[]; count: number; note: string }   409 FYERS_LOGIN_REQUIRED

// ------------------------------------------------------------------ 8. paper (thin wrapper over scanner.paper.paper_report(); cached by store version + journal mtime + costs)
export interface PaperSummary {
  key: string;                               // injected from the dict key (summary has no key)
  name: string; kind: StrategyKind | null; start: ISODate; days: number; last_date: ISODate;
  equity: number; return_pct: number | null; pnl: number;
  nifty_pct: number | null; n500_pct: number | null; excess_pct: number | null;
  expected_pct: number | null; expected_range_pct: [number | null, number | null] | null; haircut_pct: number | null;
  expected_excess_pct: number | null; haircut_excess_pct: number | null; noise_pct: number | null;
  backtest_cagr_pct: number | null; backtest_n500_cagr_pct: number | null; max_dd_pct: number | null;
  trades: number; win_rate: number | null; open: number; pending: number; fees: number; slippage: number;
  verdict: string; comparison: string | null; level: Tone;
}
// GET /api/paper
export interface PaperListResponse {
  available: boolean;
  journal: { days: number; first: ISODate; last: ISODate } | null;
  survivorship_haircut_pct: number; min_days_to_judge: number;
  strategies: PaperSummary[];
}
export interface PaperPosition { symbol: string; entry_date: ISODate; entry_price: number; qty: number; last_price: number; value: number; pnl: number; ret_pct: number; stop: number | null; days: number; via: string }
export interface PaperTrade { symbol: string; entry_date: ISODate; entry_price: number; exit_date: ISODate; exit_price: number; qty: number; pnl: number; ret_pct: number; days: number; reason: string; via: string }
// GET /api/paper/{key}
export interface PaperDetail {
  summary: PaperSummary; capital: number; cash: number;
  equity: TimeSeries;                        // ids 'paper','nifty50','nifty500' in rupees (paper_report pairs -> columnar)
  open: PaperPosition[]; trades: PaperTrade[]; pending: { action: Side; symbol: string; reason: string }[];
  trade_stats: TradeStats; expect: Record<string, unknown>; journal_days: number; last_journal: ISODate;
}

// ------------------------------------------------------------------ 9. market
// GET /api/market/movers -> { as_of: AsOf; gainers: Mover[]; losers: Mover[]; volume_spikes: Mover[] }
export interface IndexRow {                   // latest.indices.* (returns are 1-dp, percent units)
  name: string; last: number | null; chg_1d: number | null; ret_1m: number | null; ret_3m: number | null; ret_6m: number | null;
  ret_1y: number | null; cagr: number | null; max_dd: number | null; since: ISODate | null; above_50dma: boolean | null; rank: number | null;
}
export interface IndustryRow {
  industry: string; members: number; advances: number; declines: number; breadth_50: number | null;
  ret_1d_pct: number | null; ret_1w_pct: number | null; ret_1m_pct: number | null; ret_3m_pct: number | null; ret_6m_pct: number | null;
  leaders: { symbol: string; ret_3m_pct: number | null }[];
}
// GET /api/market/sectors -> { as_of: AsOf; nse_sectors: IndexRow[]; industries: IndustryRow[]; industries_source_date: ISODate }
// GET /api/market/factors -> { as_of: AsOf; factors: IndexRow[]; note: string }
export interface ResultsEvent {
  symbol: string; company: string | null; industry: string | null; date: ISODate; days_until: number; purpose: string;
  you_hold: boolean; in_models: string[]; in_orders: string[]; momentum_rank: number | null;
}
// GET /api/market/results?days=14&relevant=false -> { cached_on: ISODate | null; note: string; events: ResultsEvent[] }
//   reads the newest data/nse/events_*.json directly; filters purpose containing 'result' (case-insensitive) and universe symbols

// ------------------------------------------------------------------ 10. scan
// POST /api/scan  body { update?: boolean }  -> 202 { accepted: true; status: ScanStatus }  | 409 SCAN_BUSY details {started, by, pid}
// GET  /api/scan/history?limit=60 -> { scans: { scan_id: ISODateTime; file: string; data_date: ISODate | null; live: boolean | null; elapsed_s: number | null; strategies: number | null }[] }
// GET  /api/scan/log?lines=200&level=all|error -> { path: string; lines: string[] }   (scrubbed of access_token=/auth_code=)
// (no /api/scan/status: AppStatus.scan is the single source)

// ------------------------------------------------------------------ 11. fyers
export interface FyersStatus {
  configured: boolean; client_id_masked: string | null; plan: 'standard' | 'prime'; data_source: 'auto' | 'yahoo';
  token_present: boolean; token_created: ISODateTime | null;
  logged_in_today: boolean;                  // token.created[:10] == IST today (app.py rule)
  verified: boolean | null; verified_at: ISODateTime | null; user_name: string | null;   // only with ?verify=true (5-min cache)
  redirect_uri: string; login_modes: ('paste' | 'window')[];   // 'callback' is P2
  note: string;
}
// GET /api/fyers/status?verify=false|true
// POST /api/fyers/login body { mode: 'paste' | 'window' } -> { mode; login_url: string | null; expires_at: ISODateTime | null; instructions: string[] }
// POST /api/fyers/login/complete body { redirect_url: string } -> { ok: boolean; user_name: string | null; status: FyersStatus }

// ------------------------------------------------------------------ 12. config, costs, data health
export interface CostConfig { brokerage_pct: number; brokerage_max: number; stt_pct: number; exchange_pct: number; sebi_pct: number;
  stamp_buy_pct: number; gst_pct: number; dp_per_sell: number; slippage_pct: number; slippage_illiquid_pct: number; illiquid_below_cr: number }
export interface TaxConfig { stcg_pct: number; ltcg_pct: number; ltcg_exempt: number }
export interface ConfigView {
  account: { capital: number; min_position: number };
  data_source: 'auto' | 'yahoo'; fyers_plan: 'standard' | 'prime';
  universe: 'nifty50' | 'nifty100' | 'nifty200' | 'nifty500'; lookback_days: number;
  filters: { min_price: number; min_turnover_cr: number };
  holdings_defaults: { stop_loss_pct: number; target_pct: number };
  results: { warn_days: number }; movers_count: number; etfs: string[];
  costs: CostConfig; tax: TaxConfig;
  allocations: Record<string, number>;       // {} when the section is absent (it is absent today)
  strategies: Record<string, { enabled: boolean; params: Record<string, unknown> }>;
  telegram: { top_n: number; configured: boolean };
}
// GET /api/config -> { values: ConfigView; file_mtime: ISODateTime; needs_rescan: boolean }   (PATCH is P2)
export interface CostBreakdown { value: number; side: 'buy' | 'sell'; brokerage: number; stt: number; exchange: number; sebi: number;
  stamp: number; gst: number; dp: number; slippage: number; total: number; total_pct: number }
// GET /api/costs/preview?value=33333 -> { value: number; buy: CostBreakdown; sell: CostBreakdown; round_trip_pct: number }   (delivery only)
export interface DataHealth {               // GET /api/data/health
  store: { version: string; first_date: ISODate; last_date: ISODate; symbols: number; trading_days: number; fields: string[]; size_mb: number };
  nse: { status: string | null; complete_upto: ISODate | null };
  failed_symbols: Record<string, { count: number; last_try: ISODate }>;      // meta.failed shape (not strings)
  stale_symbols: string[]; errors: Record<string, string>;
  corporate_actions_recent: { symbol: string; date: ISODate; factor: number; reason: string }[];
  corporate_actions_total: number;
  index_history: { last_date: ISODate | null; columns: number } | null;
  results_calendar: { note: string | null; cached_on: ISODate | null };
  universe: { name: string; note: string; size: number };
  pit: { built: boolean; note: string } | null;
  journal: { exists: boolean; days: number | null; size_kb: number | null };
  logs: { path: string; size_kb: number; last_error: string | null };
  scans: { count: number; newest: ISODateTime | null; oldest: ISODateTime | null; mixed_producers: boolean };
}

// ------------------------------------------------------------------ 13. intraday (reads data/results/intraday.json from scanner/intraday/run.py; always 200)
export interface IntradayTrade {
  symbol: string; date: ISODate; side: 'LONG' | 'SHORT'; entry_time: string; entry: number; stop: number | null;
  exit_time: string; exit: number; reason: string; qty: number; pnl: number; ret_pct: number; open_now: boolean | null;
}
export interface IntradayStrategy {
  key: string; name: string; description: string; evidence: Evidence; horizon: 'intraday'; status: StrategyStatus;
  metrics: {                                 // scanner/intraday/engine.intraday_metrics
    days: number; trades: number; trades_per_day: number | null; return_pct: number | null; after_tax_return_pct: number | null;
    annualised_pct: number | null; sharpe: number | null; max_dd_pct: number | null; win_rate: number | null;
    avg_trade_pct: number | null; profit_factor: number | null; avg_day_pct: number | null;
    ci95_day_pct: [number, number] | null; t_stat: number | null; significant: boolean; start: ISODate | null; end: ISODate | null;
  };
  equity: TimeSeries;                        // rupees
  recent_trades: IntradayTrade[]; today: IntradayTrade[];
}
// GET /api/intraday
export interface IntradayResponse {
  available: boolean; reason: string | null;           // e.g. 'Intraday backtest not run yet'
  generated_at: ISODateTime | null; elapsed_s: number | null;
  data: { source: string; interval: '5m'; from: ISODate; to: ISODate; sessions: number; symbols: number; note: string } | null;
  rules: Record<string, string>;                       // server text (square-off times etc.) - never hard-coded in the UI
  sebi: { source: string; url: string; points: string[] };
  costs: { value: number; round_trip_pct: number } | null;
  strategies: IntradayStrategy[];
}
```

**Final endpoints (P1):**
- **System:** `health`, `status`
- **Overview:** `overview`, `market/breadth`
- **Strategies:** `strategies`, `strategies/{key}`, `strategies/{key}/curve`, `strategies/{key}/trades`
- **Signals and lookups:** `signals`, `screener` (B2), `sparklines`, `symbols`, `chart/{symbol}`, `stock/{symbol}`
- **Holdings:** GET and PUT `holdings`, POST `holdings/import/fyers`
- **Paper:** `paper`, `paper/{key}`
- **Market:** `market/movers`, `market/sectors`, `market/factors`, `market/results`
- **Scan:** POST `scan`, `scan/history`, `scan/log`
- **Fyers:** `fyers/status`, `fyers/login`, `fyers/login/complete`
- **Settings:** `config`, `costs/preview`, `data/health`
- **Intraday:** `intraday`

P2: PATCH `config`, `quotes`, `fyers/callback`.

New backend items: **B9** (artifacts first, `latest.json` last as the commit marker, Windows-safe replace) and **B10** (`producer`/commit field in `latest.json`). B6 can be removed from the list because the merge already happened.