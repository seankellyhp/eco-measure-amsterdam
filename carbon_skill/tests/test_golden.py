"""The report text must not change when storage changes.

The golden files were written by the CSV/JSON code (step 0 of sqlite_plan.md),
before the database existed; these tests now render the same runs from it.
Regenerate only on purpose: CARBON_UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""

import os
import time
from pathlib import Path

import pytest

from carbon_skill import db, paths, report, runs

from legacy_fixture import write_run, write_transcript

GOLDEN = Path(__file__).parent / "golden"

pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs a settable local time zone")


@pytest.fixture(autouse=True)
def _amsterdam(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Amsterdam")
    monkeypatch.setenv("NO_COLOR", "1")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _check(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("CARBON_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text)
    assert text == path.read_text()


def _render(label: str) -> str:
    run = runs.find(label)
    return "\n".join(report.render(run, live=False)) + "\n"


def test_report_with_session(tmp_path):
    t = write_transcript(tmp_path / "s.jsonl")
    write_run(paths.data_root(), "golden", t)
    db.connect().close()  # a new database imports the folder, saving its usage
    run = runs.find("golden")
    assert run["usage_saved_at"] and run["ecologits_version"]
    _check("report_with_session.txt", _render("golden"))
    # Saved when the run ended: the report no longer needs the transcript.
    t.unlink()
    _check("report_with_session.txt", _render("golden"))


def test_report_live_path_matches_stored(tmp_path):
    """Usage read from the transcript (as for a live run) renders the same text."""
    t = write_transcript(tmp_path / "s.jsonl")
    write_run(paths.data_root(), "golden", t)
    db.connect().close()
    run = runs.find("golden")
    db.update_run(run["id"], usage_saved_at=None, usage_note="test: force the transcript path")
    _check("report_with_session.txt", _render("golden"))


def test_report_without_session():
    write_run(paths.data_root(), "nosession", None)
    db.connect().close()
    assert runs.find("nosession")["usage_note"]
    _check("report_without_session.txt", _render("nosession"))
