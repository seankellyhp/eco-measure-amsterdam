import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest


def carbon(*args, **kw):
    return subprocess.run([sys.executable, "-m", "carbon_skill", *args],
                          capture_output=True, text=True, timeout=90, **kw)


def _call(i: int) -> str:
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return json.dumps({"uuid": f"a{i}", "timestamp": ts, "message": {
        "id": f"m{i}", "model": "claude-opus-5",
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 200}}}) + "\n"


@pytest.mark.slow
def test_start_report_end(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("")
    env = {**os.environ, "CARBON_MEASURE_SECS": "3", "CARBON_PARENT_PID": str(os.getpid()),
           "CARBON_SESSION_TRANSCRIPT": str(transcript)}
    r = carbon("start", "t1", env=env)  # output captured through a pipe: must still return
    assert r.returncode == 0, r.stderr
    assert "as @1" in r.stdout
    assert carbon("start", "t1", env=env).returncode == 1
    time.sleep(2)
    with open(transcript, "a") as fh:
        fh.write(_call(1))
        fh.write(_call(2))
    time.sleep(6)
    r = carbon("report", env=env)  # no label: this session's run
    assert r.returncode == 0 and "[LIVE" in r.stdout and "API calls" in r.stdout, r.stderr
    r = carbon("end", env=env)
    assert r.returncode == 0 and "CodeCarbon report - 't1'" in r.stdout, r.stderr

    root = tmp_path / "runs"
    assert not list(root.rglob("emissions.csv")) and not list(root.rglob("*.json"))
    from carbon_skill import db
    run = db.get_run(1)
    assert run["state"] == "stopped" and run["stopped_by"] == "carbon end"
    assert run["usage_saved_at"] and run["cpu_model"]

    # The tokens were saved when the run ended, so the transcript is no longer needed.
    transcript.unlink()
    r = carbon("report", "@1", env=env)
    assert r.returncode == 0 and "API calls                  2" in r.stdout, r.stdout + r.stderr

    # A second run with the same label keeps the first.
    assert carbon("start", "t1", env=env).returncode == 0
    r = carbon("end", "t1", env=env)
    assert r.returncode == 0, r.stderr
    r = carbon("list", env=env)
    assert r.returncode == 0 and r.stdout.count(" t1 ") == 2, r.stdout
