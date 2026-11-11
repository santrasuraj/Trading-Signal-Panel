"""Market calendar, tax harvesting, options strategy builder, portfolio risk."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path, Query
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models.common import Model
from ..services import calendar_svc, fund_svc, journal_svc, layouts_svc, optbt_svc, payoff_svc, risk_svc, setups_svc, tax_svc

router = APIRouter(prefix="/api", tags=["desk"])


@router.get("/calendar", response_model=None, response_class=SafeJSONResponse)
def calendar(days: int = Query(30, ge=1, le=calendar_svc.MAX_DAYS)):
    """Results, ex-dividend / rights / bonus / split / buyback dates, F&O expiries and market holidays, nearest first."""
    return calendar_svc.calendar(days)


@router.get("/tax", response_model=None, response_class=SafeJSONResponse)
def tax(st: float | None = Query(None, ge=-1e10, le=1e10), lt: float | None = Query(None, ge=-1e10, le=1e10)):
    """Your lots as short / long term, this financial year's tax, and gain / loss harvesting before 31 March.
    `st` / `lt`: net short / long-term gains already booked this year (losses negative); default: Quant Desk's
    recorded real orders."""
    return tax_svc.view(st, lt)


class PayoffLeg(Model):
    kind: Literal["CE", "PE", "FUT"]
    side: Literal["buy", "sell"]
    strike: float | None = Field(None, ge=0, le=1e7)
    lots: int = Field(1, ge=1, le=500)
    price: float | None = Field(None, ge=0, le=1e7)
    iv_pct: float | None = Field(None, gt=0, le=500)


class PayoffBody(Model):
    symbol: str = Field(..., max_length=25)
    expiry: str | None = Field(None, max_length=10)
    legs: list[PayoffLeg] = Field(..., min_length=1, max_length=payoff_svc.MAX_LEGS)
    days: float = Field(0, ge=0, le=400)
    iv_shift: float = Field(0, ge=-50, le=100)
    lot: int | None = Field(None, ge=1, le=100000)


@router.post("/options/payoff", response_model=None, response_class=SafeJSONResponse)
def options_payoff(body: PayoffBody):
    """Profit and loss of a multi-leg options position on a stored chain: at expiry and today, breakevens, maximum
    profit / loss, Greeks and the chance of profit."""
    return payoff_svc.build(body.symbol.upper(), body.expiry, [x.model_dump() for x in body.legs], days=body.days,
                            iv_shift=body.iv_shift, lot=body.lot)


@router.get("/risk", response_model=None, response_class=SafeJSONResponse)
def risk():
    """Money at risk to your stops, concentration, beta, one-day loss estimate, stress and correlation."""
    return risk_svc.view()


@router.get("/setups", response_model=None, response_class=SafeJSONResponse)
def live_setups(kinds: str | None = Query(None, max_length=300), scope: Literal["all", "mine"] = "all",
                limit: int = Query(200, ge=1, le=setups_svc.LIMIT_MAX)):
    """Today's intraday events (gaps, opening-range breaks, fresh highs / lows, VWAP crosses, volume spikes, 52-week
    breaks) from the live bars, newest first. `kinds`: comma-separated; `scope=mine`: watchlists and holdings."""
    ks = [k for k in (kinds or "").split(",") if k]
    return setups_svc.view(ks or None, scope, limit)


@router.get("/trail/{symbol}", response_model=None, response_class=SafeJSONResponse)
def trail(symbol: str = Path(..., max_length=25), pct: float = Query(8.0, gt=0, le=50)):
    """A trailing-stop suggestion for a real holding: `pct` under the highest close since it was bought."""
    return risk_svc.trail_suggestion(symbol, pct)


class JournalNote(Model):
    setup: str | None = Field(None, max_length=60)
    tags: list[str] | None = Field(None, max_length=12)
    mistakes: list[str] | None = Field(None, max_length=12)
    notes: str | None = Field(None, max_length=4000)
    rating: int | None = Field(None, ge=0, le=5)
    image: str | None = Field(None, max_length=journal_svc.MAX_IMAGE)


@router.get("/journal", response_model=None, response_class=SafeJSONResponse)
def journal(source: Literal["all", "real", "practice", "replay"] = "all"):
    """Every trade (real fills, practice account, replays) with your notes, and the statistics by setup, mistake,
    hour, weekday, holding time and side, plus how far trades went against / for you while open."""
    return journal_svc.view(source)


@router.put("/journal/{trade_id}", response_model=None, response_class=SafeJSONResponse)
def journal_note(body: JournalNote, trade_id: str = Path(..., pattern=r"^[0-9a-f]{12}$")):
    """Your setup tag, tags, mistakes, notes, 0-5 rating and a chart screenshot for one trade."""
    return journal_svc.save_note(trade_id, body.model_dump(exclude_unset=True))


@router.get("/journal/{trade_id}/image", response_model=None, response_class=SafeJSONResponse)
def journal_image(trade_id: str = Path(..., pattern=r"^[0-9a-f]{12}$")):
    return {"image": journal_svc.image(trade_id)}


@router.get("/announcements", response_model=None, response_class=SafeJSONResponse)
def announcements(symbol: str | None = Query(None, max_length=25), days: int = Query(3, ge=1, le=30),
                  routine: bool = False, limit: int = Query(100, ge=1, le=300)):
    """NSE company announcements of the last `days` days: one stock (`symbol`) or your holdings and watchlists."""
    return calendar_svc.announcements(symbol, days, routine, limit)


class OptBtSpec(Model):
    underlying: Literal["NIFTY", "BANKNIFTY"] = "NIFTY"
    strategy: Literal["short_straddle", "short_strangle", "iron_condor", "iron_fly", "bull_put", "bear_call",
                      "long_straddle", "long_strangle", "bull_call", "bear_put"] = "iron_condor"
    cycle: Literal["monthly", "weekly"] = "monthly"
    entry_dte: int = Field(30, ge=1, le=60)
    short_pct: float = Field(2.0, ge=0, le=15)
    wing_pct: float = Field(4.0, ge=0, le=20)
    stop_pct: float | None = Field(None, gt=0, le=1000)
    target_pct: float | None = Field(None, gt=0, le=100)
    lots: int = Field(1, ge=1, le=100)
    slippage_pct: float = Field(1.0, ge=0, le=10)


class HistoryBody(Model):
    days: int = Field(500, ge=20, le=750)


@router.get("/options-backtest/status", response_model=None, response_class=SafeJSONResponse)
def optbt_status():
    """Stored option history (days, range) and the background fetch's progress."""
    return optbt_svc.status()


@router.post("/options-backtest/history", response_model=None, response_class=SafeJSONResponse)
def optbt_history(body: HistoryBody):
    """Fetch NSE's daily index-option prices for the last `days` trading days not stored yet (background)."""
    return optbt_svc.start_history(body.days)


@router.post("/options-backtest/run", response_model=None, response_class=SafeJSONResponse)
def optbt_run(body: OptBtSpec):
    """Backtest an options strategy, one position per expiry cycle, on the stored daily option prices."""
    return optbt_svc.run(body.model_dump())


@router.get("/fundamentals-status", response_model=None, response_class=SafeJSONResponse)
def fundamentals_status():
    """How many companies' numbers are stored, and the background fetch's progress."""
    return fund_svc.status()


@router.post("/fundamentals/refresh", response_model=None, response_class=SafeJSONResponse)
def fundamentals_refresh():
    """Fetch every universe company's last quarters from NSE in the background (skips ones checked recently)."""
    return fund_svc.start_refresh()


@router.get("/fundamentals/{symbol}", response_model=None, response_class=SafeJSONResponse)
def fundamentals(symbol: str = Path(..., max_length=25)):
    """A company's quarterly revenue, profit, EPS, growth, margin and P/E from NSE's filings."""
    return fund_svc.view(symbol)


class ChartLayout(Model):
    name: str = Field(..., min_length=1, max_length=40)
    ind: list[str] = Field([], max_length=40)
    log: bool = False
    lines: bool = True
    ctype: str = Field("candles", max_length=20)
    tf: str = Field("1d", max_length=4)
    range: str = Field("1y", max_length=4)
    levels: list[str] = Field([], max_length=20)


class ChartLayouts(Model):
    layouts: list[ChartLayout] = Field([], max_length=30)


@router.get("/chart-layouts", response_model=None, response_class=SafeJSONResponse)
def chart_layouts():
    """Your saved chart layouts (indicators, chart type, timeframe, options), applied to any stock."""
    return layouts_svc.read()


@router.put("/chart-layouts", response_model=None, response_class=SafeJSONResponse)
def put_chart_layouts(body: ChartLayouts):
    return layouts_svc.write([x.model_dump() for x in body.layouts])


class FormulaItem(Model):
    id: str | None = Field(None, max_length=8)
    name: str = Field(..., min_length=1, max_length=40)
    expr: str = Field(..., min_length=1, max_length=300)
    pane: Literal["price", "own"] = "own"


class FormulasBody(Model):
    formulas: list[FormulaItem] = Field([], max_length=30)


class FormulaCheck(Model):
    expr: str = Field(..., max_length=300)
    symbol: str = Field("NIFTY50", max_length=25)


def _formula_error(e: Exception):
    from ..errors import ApiException
    return ApiException("VALIDATION", str(e))


@router.get("/formulas", response_model=None, response_class=SafeJSONResponse)
def formulas():
    """Your saved formulas (custom indicators) and the functions a formula may use."""
    from scanner import formula
    return {"formulas": formula.saved(), "functions": formula.help_text(), "fields": list(formula.FIELDS)}


@router.put("/formulas", response_model=None, response_class=SafeJSONResponse)
def put_formulas(body: FormulasBody):
    """Save your formulas (each becomes a scan field in 'Your formulas')."""
    from scanner import formula
    try:
        return {"formulas": formula.save_all([x.model_dump() for x in body.formulas])}
    except formula.FormulaError as e:
        raise _formula_error(e) from e


@router.post("/formulas/check", response_model=None, response_class=SafeJSONResponse)
def check_formula(body: FormulaCheck):
    """Check a formula and show its last values on one stock."""
    from scanner import formula
    from ..services import chart_data
    try:
        df = chart_data.bars_frame(body.symbol.upper())
        v = formula.evaluate(body.expr, {k: df[k] for k in formula.FIELDS}).dropna()
    except formula.FormulaError as e:
        raise _formula_error(e) from e
    return {"ok": True, "symbol": body.symbol.upper(),
            "last": [{"t": d.date().isoformat(), "v": round(float(x), 4)} for d, x in v.iloc[-5:].items()]}


@router.get("/formula-series/{symbol}", response_model=None, response_class=SafeJSONResponse)
def formula_series(symbol: str = Path(..., max_length=25), expr: str = Query(..., max_length=300),
                   range: Literal["3m", "6m", "1y", "2y", "5y", "max"] = "1y"):
    """A formula's values on one stock's daily bars over the chart's range (computed on the full history)."""
    from scanner import formula
    from ..services import chart_data
    try:
        df = chart_data.bars_frame(symbol.upper())
        v = formula.evaluate(expr, {k: df[k] for k in formula.FIELDS})
    except formula.FormulaError as e:
        raise _formula_error(e) from e
    days = chart_data.RANGE_DAYS[range]
    if days is not None:
        v = v[v.index >= v.index[-1] - __import__("pandas").Timedelta(days=days)]
    return {"symbol": symbol.upper(), "t": [d.date().isoformat() for d in v.index],
            "v": [None if x != x else round(float(x), 4) for x in v.to_numpy()]}
