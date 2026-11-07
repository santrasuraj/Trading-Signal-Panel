"""NSE event calendar and holiday parsing (scanner/events.py), with NSE's replies stubbed: no network."""
from datetime import date

from scanner import events


def _stub(monkeypatch, rows):
    monkeypatch.setattr(events, "_cached", lambda name, max_age_s, fetch, expect=list: rows)


def test_nse_date_blank_or_bad_is_none():
    """A blank string parses to NaT without raising, and NaT can't be compared with a date."""
    assert events._nse_date("05-Nov-2026") == date(2026, 11, 5)
    assert events._nse_date("05-NOV-2026") == date(2026, 11, 5)
    for bad in ("", "   ", None, "nan", "2026-11-05", "31-Feb-2026"):
        assert events._nse_date(bad) is None, bad


def test_upcoming_results_skips_a_blank_date(monkeypatch):
    """A results row with an empty date used to raise TypeError (NaT vs date) and abort the whole daily scan."""
    _stub(monkeypatch, [
        {"symbol": "AAA", "purpose": "Financial Results", "date": ""},
        {"symbol": "BBB", "purpose": "Financial Results"},                      # no date key at all
        {"symbol": "CCC", "purpose": "Financial Results", "date": "10-Nov-2026"},
        {"symbol": "CCC", "purpose": "Financial Results", "date": "08-Nov-2026"},
        {"symbol": "DDD", "purpose": "Dividend", "date": "09-Nov-2026"},
    ])
    out, note = events.upcoming_results(["AAA", "BBB", "CCC", "DDD"], date(2026, 11, 7), days=14)
    assert out == {"CCC": "2026-11-08"}
    assert "1 of your stocks" in note


def test_results_history_never_stores_nat(monkeypatch):
    """A blank date used to be stored as the string 'NaT', which made the scan skip results-date renames."""
    _stub(monkeypatch, [
        {"symbol": "AAA", "purpose": "Financial Results", "date": ""},
        {"symbol": "AAA", "purpose": "Financial Results", "date": "05-Oct-2026"},
    ])
    out = events.results_history(date(2026, 10, 1), date(2026, 10, 31), log=lambda *a: None)
    assert out == {"AAA": ["2026-10-05"]}
    for days in out.values():
        for d in days:
            date.fromisoformat(d)


def test_trading_holidays_skip_a_blank_date(monkeypatch):
    _stub(monkeypatch, {"CM": [{"tradingDate": ""}, {"tradingDate": "25-Dec-2026"}, {"tradingDate": "26-Jan-2027"}]})
    assert events.trading_holidays(2026) == {"2026-12-25"}
