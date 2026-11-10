import json
import os
import subprocess
import sys
import time

import pytest


def carbon(*args, **kw):
    return subprocess.run([sys.executable, "-m", "carbon_skill", *args],
                          capture_output=True, text=True, timeout=90, **kw)


@pytest.mark.slow
def test_start_report_end(tmp_path):
    env = {**os.environ, "CARBON_MEASURE_SECS": "3", "CARBON_PARENT_PID": str(os.getpid())}
    r = carbon("start", "t1", env=env)  # output captured through a pipe: must still return
    assert r.returncode == 0, r.stderr
    assert carbon("start", "t1", env=env).returncode == 1
    time.sleep(8)
    r = carbon("report", "t1", env=env)
    assert r.returncode == 0 and "[LIVE" in r.stdout, r.stderr
    r = carbon("end", "t1", env=env)
    assert r.returncode == 0 and "CodeCarbon report - 't1'" in r.stdout, r.stderr
    status = json.loads((tmp_path / "runs" / "t1" / "status.json").read_text())
    assert status["state"] == "stopped" and status["stopped_by"] == "carbon end"
