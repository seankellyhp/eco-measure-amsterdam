"""A pre-database run folder (run.json, status.json, session.json, emissions.csv)
and the Claude Code transcript it points at. Shared by the golden and import tests."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HEADER = (
    "timestamp,project_name,run_id,experiment_id,duration,emissions,emissions_rate,cpu_power,gpu_power,"
    "ram_power,cpu_energy,gpu_energy,ram_energy,energy_consumed,water_consumed,country_name,country_iso_code,"
    "region,cloud_provider,cloud_region,os,python_version,codecarbon_version,cpu_count,cpu_model,gpu_count,"
    "gpu_model,longitude,latitude,ram_total_size,tracking_mode,cpu_utilization_percent,gpu_utilization_percent,"
    "ram_utilization_percent,ram_used_gb,on_cloud,pue,wue"
).split(",")

T0 = datetime(2026, 11, 10, 9, 0, 0, tzinfo=timezone.utc)
START = "2026-11-10T10:00:00+01:00"
END = "2026-11-10T10:30:00+01:00"

# (minutes after T0, model, fresh, cache_read, cache_write, output, sidechain, latency s)
CALLS = [
    (1, "claude-opus-5", 12, 20_000, 3_000, 450, False, 6.5),
    (2, "claude-opus-5", 3, 23_000, 900, 1_200, False, 14.0),
    (4, "claude-opus-5-1", 5, 24_000, 1_100, 300, False, 4.25),
    (7, "claude-haiku-4-5", 40, 8_000, 2_000, 150, True, 2.0),
    (9, "claude-opus-5", 2, 25_500, 600, 2_400, False, None),
    (13, "claude-opus-4-1-20250805", 1, 26_000, 700, 800, False, 9.0),
    (18, "mystery-model", 100, 0, 0, 77, False, 1.0),
    (25, "claude-opus-5", 4, 27_000, 500, 600, False, 7.75),
]


def write_transcript(path: Path, calls=CALLS) -> Path:
    lines = []
    for i, (minute, model, fresh, cread, cwrite, out, side, lat) in enumerate(calls):
        sent = T0 + timedelta(minutes=minute)
        lines.append({"uuid": f"u{i}", "timestamp": sent.isoformat().replace("+00:00", "Z")})
        usage = {"input_tokens": fresh, "cache_read_input_tokens": cread,
                 "cache_creation_input_tokens": cwrite, "output_tokens": out}
        done = sent + timedelta(seconds=lat if lat is not None else 0)
        rec = {"uuid": f"a{i}", "parentUuid": f"u{i}" if lat is not None else "missing",
               "timestamp": done.isoformat().replace("+00:00", "Z"), "isSidechain": side,
               "message": {"id": f"m{i}", "model": model, "usage": usage}}
        lines.append(rec)
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


def _row(seq: int, run_id: str) -> dict:
    d = 10.0 * (seq + 1)
    cpu, gpu, ram = 0.00004 * (seq + 1), 0.00005 * (seq + 1), 0.000055 * (seq + 1)
    e = cpu + gpu + ram
    return {
        "timestamp": f"2026-11-10T10:00:{10 * (seq + 1):02d}" if seq < 5 else "2026-11-10T10:01:00",
        "project_name": "golden", "run_id": run_id,
        "experiment_id": "5b0fa12a-3dd7-45bb-9766-cc326314d9f1",
        "duration": d, "emissions": e * 0.38, "emissions_rate": e * 0.38 / d,
        "cpu_power": 14.25 + seq, "gpu_power": 10.5, "ram_power": 20.0,
        "cpu_energy": cpu, "gpu_energy": gpu, "ram_energy": ram, "energy_consumed": e,
        "water_consumed": 0.0, "country_name": "Netherlands", "country_iso_code": "NLD", "region": "",
        "cloud_provider": "", "cloud_region": "", "os": "Linux-6.8.0-x86_64-with-glibc2.35",
        "python_version": "3.12.12", "codecarbon_version": "3.3.2", "cpu_count": 24,
        "cpu_model": "13th Gen Intel(R) Core(TM) i7-13700K", "gpu_count": 1,
        "gpu_model": "1 x NVIDIA GeForce RTX 3090 Ti", "longitude": "", "latitude": "",
        "ram_total_size": 62.580135345458984, "tracking_mode": "machine",
        "cpu_utilization_percent": 1.13, "gpu_utilization_percent": 2.7,
        "ram_utilization_percent": 11.1, "ram_used_gb": 6.94, "on_cloud": "N", "pue": 1.0, "wue": 0.0,
    }


def write_run(root: Path, label: str, transcript: Path | None) -> Path:
    """A finished run folder as `carbon` 0.3 left it. An earlier run_id comes first
    in the CSV, as when a label was reused, so only the last run_id must count."""
    rundir = Path(root) / label
    rundir.mkdir(parents=True)
    rows = [_row(0, "old-run")] + [_row(i, "cc-run-42") for i in range(6)]
    with open(rundir / "emissions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    (rundir / "run.json").write_text(json.dumps({
        "label": label, "measure_secs": 10.0,
        "grid": {"country": "NLD", "region": None, "description": "CARBON_COUNTRY"},
        "agent": {"pid": 999999999, "create_time": 1.0, "name": "claude", "how": "CLAUDE_PID"},
        "cwd": "/tmp", "version": "0.3.0",
    }))
    (rundir / "status.json").write_text(json.dumps({
        "state": "stopped", "pid": 999999998, "create_time": 1.0, "started_at": START,
        "cpu_method": "RAPL", "gpu_method": "pynvml", "last_flush_at": END, "ended_at": END,
        "stopped_by": "carbon end",
    }))
    if transcript is not None:
        (rundir / "session.json").write_text(json.dumps({
            "harness": "claude-code", "id": "sess-golden", "transcript": str(transcript),
            "how": "$CLAUDE_CODE_SESSION_ID",
        }))
    (rundir / "monitor.log").write_text("CPU Tracking Method: RAPL\nGPU Tracking Method: pynvml\n")
    return rundir
