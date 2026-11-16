"""Economic calendar: the dated macro events that move Indian markets.

  * Fixed schedules, published in advance (update each year):
      - RBI Monetary Policy Committee decisions, FY 2026-27 (RBI press release under Section 45ZI of the RBI Act):
        8 Apr, 5 Jun, 5 Aug, 7 Oct, 4 Dec 2026, 5 Feb 2027 (10:00 IST);
      - US Federal Reserve (FOMC) decisions, 2026 and 2027 (the Fed's calendar; 2027 is tentative until each meeting is
        confirmed). The decision comes at 14:00 New York time: about 23:30 / 00:30 IST, so India trades it the next day.
  * Release rules of India's statistics office (MOSPI) and the Budget:
      - Consumer prices (CPI): the 12th of each month, 16:00 (the next working day when the 12th is a weekend);
      - Wholesale prices (WPI, commerce ministry): the 14th, 12:00;
      - Industrial production (IIP): the 28th, 16:00;
      - GDP: the last working day of February, May, August and November, 16:00;
      - Union Budget: 1 February.
    A rule can be off by a day when a release moves for a holiday: the official calendars have the final word.
  * Your own events: data/econ_events.json, a list of {"date": "YYYY-MM-DD", "name": ..., "detail": ...}.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

RBI = ("2026-04-08", "2026-06-05", "2026-08-05", "2026-10-07", "2026-12-04", "2027-02-05")
FOMC = ("2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08")
USER_FILE = "econ_events.json"


def _workday_on_or_after(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _last_workday(y: int, m: int) -> date:
    d = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _prev_month(y: int, m: int) -> str:
    return date(y - (m == 1), 12 if m == 1 else m - 1, 1).strftime("%B")


def events(start: date, end: date, data_dir: Path | None = None) -> list[dict]:
    """[{date, name, country, importance high/medium, time, detail, source}] between start and end, by date."""
    out: list[dict] = []

    def add(d: date, name: str, country: str, imp: str, time: str, detail: str, source: str):
        if start <= d <= end:
            out.append({"date": d.isoformat(), "name": name, "country": country, "importance": imp, "time": time,
                        "detail": detail, "source": source})

    for s in RBI:
        add(date.fromisoformat(s), "RBI policy decision", "IN", "high", "10:00",
            "Repo rate and stance: banks, NBFCs and rate-sensitive stocks move most", "RBI's published schedule")
    for s in FOMC:
        d = date.fromisoformat(s)
        add(d + timedelta(days=1), "US Fed decision (overnight)", "US", "high", "~00:00",
            "Announced at 14:00 New York time on " + d.strftime("%d %b") + "; Indian markets react this morning",
            "Federal Reserve calendar" + (" (tentative)" if d.year >= 2027 else ""))
    for y, m in _months(start - timedelta(days=31), end):
        add(_workday_on_or_after(date(y, m, 12)), "India CPI inflation", "IN", "high", "16:00",
            f"Consumer prices for {_prev_month(y, m)}", "MOSPI release rule")
        add(_workday_on_or_after(date(y, m, 14)), "India WPI inflation", "IN", "medium", "12:00",
            f"Wholesale prices for {_prev_month(y, m)}", "Commerce ministry release rule")
        add(_workday_on_or_after(date(y, m, 28)), "India industrial production (IIP)", "IN", "medium", "16:00",
            f"Factory output for {_prev_month(y, m)}", "MOSPI release rule")
        if m in (2, 5, 8, 11):
            add(_last_workday(y, m), "India GDP", "IN", "high", "16:00", "Quarterly growth estimate", "MOSPI release rule")
        if m == 2:
            add(date(y, 2, 1), "Union Budget", "IN", "high", "11:00", "Tax and spending plans for the next financial year",
                "Budget day by convention")
    p = (data_dir / USER_FILE) if data_dir else None
    if p and p.exists():
        try:
            for e in json.loads(p.read_text(encoding="utf-8")):
                d = date.fromisoformat(str(e["date"]))
                add(d, str(e.get("name") or "Event")[:80], str(e.get("country") or ""), str(e.get("importance") or "medium"),
                    str(e.get("time") or ""), str(e.get("detail") or "")[:200], "your econ_events.json")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return sorted(out, key=lambda e: (e["date"], e["name"]))
