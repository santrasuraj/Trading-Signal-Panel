"""Automatic jobs (web/api/services/automation_svc.py): Task Scheduler status read by position from schtasks' CSV, a
one-click setup that runs setup_schedule.ps1, and the job list kept in step with that script. subprocess is faked:
the real Task Scheduler is never touched."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from web.api.errors import ApiException
from web.api.services import automation_svc as auto

ROOT = Path(__file__).resolve().parent.parent
HEADER = '"HostName","TaskName","Next Run Time","Status","Logon Mode","Last Run Time","Last Result","Author"\n'


def row(name, nxt="09-11-2026 08:30:00", status="Ready", last="06-11-2026 15:40:10", result="0"):
    return HEADER + f'"PC","\\{name}","{nxt}","{status}","Interactive only","{last}","{result}","me"\n'


@pytest.fixture
def fake_tasks(monkeypatch):
    """schtasks answers for the names in `have`; any other name is 'not found' (exit code 1)."""
    have: dict[str, str] = {}
    calls: list[list[str]] = []

    def run(args, **kw):
        calls.append(list(args))
        if args[0] == "schtasks":
            name = args[args.index("/tn") + 1]
            if name in have:
                return SimpleNamespace(returncode=0, stdout=have[name], stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: The system cannot find the file specified.")
        return SimpleNamespace(returncode=0, stdout="Created task: x\nDone.\n", stderr="")

    monkeypatch.setattr(auto.subprocess, "run", run)
    monkeypatch.setattr(auto.os, "name", "nt")
    auto._cache.update(at=0.0, status=None)
    yield SimpleNamespace(have=have, calls=calls)
    auto._cache.update(at=0.0, status=None)


def test_status_reads_each_job_and_counts_the_missing(fake_tasks):
    fake_tasks.have["NSE Scanner 0830"] = row("NSE Scanner 0830")
    fake_tasks.have["NSE Scanner live"] = row("NSE Scanner live", result="-2147020576")       # 0x800710E0
    fake_tasks.have["NSE Scanner pattern study"] = row("NSE Scanner pattern study", last="N/A", result="267011")
    s = auto.status()
    by = {j["name"]: j for j in s["jobs"]}
    assert s["available"] and s["missing"] == len(auto.JOBS) - 3
    a = by["NSE Scanner 0830"]
    assert a["registered"] and a["state"] == "Ready" and a["next_run"] == "2026-11-09T08:30" and a["last_result"] == "ok" and a["ok"]
    assert by["NSE Scanner live"]["ok"] is False and "did not start" in by["NSE Scanner live"]["last_result"]
    p = by["NSE Scanner pattern study"]
    assert p["last_run"] is None and p["last_result"] == "not run yet" and p["ok"] is None
    assert not by["NSE Scanner option chains"]["registered"]
    n = len(fake_tasks.calls)
    auto.status()                                               # cached for a minute
    assert len(fake_tasks.calls) == n
    auto.status(refresh=True)
    assert len(fake_tasks.calls) == n + len(auto.JOBS)


def test_setup_runs_the_script_without_a_window(fake_tasks, monkeypatch, tmp_path):
    (tmp_path / "setup_schedule.ps1").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(auto.P, "root", tmp_path)
    for n, _, _ in auto.JOBS:
        fake_tasks.have[n] = row(n)
    r = auto.setup()
    ps = next(c for c in fake_tasks.calls if c[0] == "powershell")
    assert ps[:6] == ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
    assert ps[6] == str(tmp_path / "setup_schedule.ps1")
    assert r["ok"] and r["status"]["missing"] == 0 and r["output"][-1] == "Done."


def test_setup_refuses_a_git_worktree_copy(fake_tasks, monkeypatch, tmp_path):
    wt = tmp_path / ".worktrees" / "branch"
    wt.mkdir(parents=True)
    (wt / "setup_schedule.ps1").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(auto.P, "root", wt)
    with pytest.raises(ApiException) as e:
        auto.setup()
    assert e.value.code == "VALIDATION"
    assert not any(c[0] == "powershell" for c in fake_tasks.calls)


def test_the_job_list_matches_setup_schedule():
    """Every job the page lists is one setup_schedule.ps1 registers, and the other way round."""
    ps = (ROOT / "setup_schedule.ps1").read_text(encoding="utf-8")
    script = set(re.findall(r'Name = "(NSE Scanner [^"]+)"', ps)) | set(re.findall(r'-TaskName "(NSE Scanner [^"*]+)"', ps))
    times = re.search(r'foreach \(\$t in @\(([^)]*)\)\)', ps).group(1)
    script |= {f"NSE Scanner {t.replace(':', '')}" for t in re.findall(r'"(\d\d:\d\d)"', times)}
    assert {n for n, _, _ in auto.JOBS} == script


def test_history_download_job_stops_clearly_without_fyers(monkeypatch):
    """The background job (intraday_job --backfill) fails with a reason the page can show, never silently."""
    from scanner import providers
    from web.api.services import intraday_job
    monkeypatch.setattr(providers, "get_fyers", lambda cfg: (None, "not logged in today"))
    msgs = []
    with pytest.raises(RuntimeError, match="log in to Fyers first"):
        intraday_job._backfill({}, lambda **kw: msgs.append(kw))
    assert msgs == []


def test_dates_in_other_formats_and_unknown_codes():
    assert auto._when("11/09/2026 8:30:00 AM") == "2026-11-09T08:30"
    assert auto._when("N/A") is None and auto._when("") is None
    assert auto._when("Montag 9.11.") == "Montag 9.11."                 # shown as Windows printed it
    assert auto._result("1") == ("failed (code 0x1)", False)
    assert auto._result(None) == (None, None)


def test_status_reports_the_served_ui_build(monkeypatch, tmp_path):
    """A tab compares its own entry script with this: a different one means it runs an older build."""
    from web.api.routers import system
    idx = tmp_path / "index.html"
    idx.write_text('<script type="module" crossorigin src="/assets/index-AbC_12-x.js"></script>', encoding="utf-8")
    monkeypatch.setattr(system, "UI_INDEX", idx)
    monkeypatch.setattr(system, "_ui", {"mtime": None, "build": None})
    assert system.ui_build() == "index-AbC_12-x.js"
    monkeypatch.setattr(system, "UI_INDEX", tmp_path / "missing.html")
    assert system.ui_build() is None


def test_server_watcher_sees_code_changes(tmp_path, monkeypatch):
    """--reload restarts the server when a watched .py file changes, and only for the app's own code."""
    import os
    from web import serve
    (tmp_path / "a").mkdir()
    f = tmp_path / "a" / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "a" / "data.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(serve, "WATCH_DIRS", [tmp_path / "a"])
    snap = serve.code_snapshot()
    assert list(snap) == [str(f)]
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
    assert serve.code_snapshot() != snap
    assert {d.name for d in serve.WATCH_DIRS} == {"a"}


def test_real_watch_dirs_are_the_apps_code():
    from web import serve
    assert [d.relative_to(serve.ROOT).as_posix() for d in serve.WATCH_DIRS] == ["web/api", "scanner"]
