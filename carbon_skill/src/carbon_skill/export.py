"""carbon export: one run's samples as CodeCarbon's emissions.csv, or the whole
database as SQL text."""

from __future__ import annotations

import csv
import io
import sys
from datetime import datetime

from . import db, paths, runs

# CodeCarbon 3.3.2's emissions.csv header, in its order.
CSV_HEADER = [
    "timestamp", "project_name", "run_id", "experiment_id", "duration", "emissions", "emissions_rate",
    "cpu_power", "gpu_power", "ram_power", "cpu_energy", "gpu_energy", "ram_energy", "energy_consumed",
    "water_consumed", "country_name", "country_iso_code", "region", "cloud_provider", "cloud_region", "os",
    "python_version", "codecarbon_version", "cpu_count", "cpu_model", "gpu_count", "gpu_model", "longitude",
    "latitude", "ram_total_size", "tracking_mode", "cpu_utilization_percent", "gpu_utilization_percent",
    "ram_utilization_percent", "ram_used_gb", "on_cloud", "pue", "wue",
]


def _cell(key: str, value) -> str:
    if value is None:
        return ""
    if key in ("cpu_count", "gpu_count") and isinstance(value, float) and value.is_integer():
        return str(int(value))  # CodeCarbon writes counts as integers
    return repr(value) if isinstance(value, float) else str(value)


def _local(ts: str) -> str:
    """CodeCarbon writes local time without an offset."""
    try:
        return datetime.fromisoformat(ts).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return ts


def csv_text(run: dict) -> str:
    """The run's samples with CodeCarbon's column names. Columns this program
    does not keep (location, cloud, country name, wue) are left empty."""
    static = {cc: run.get(col) for cc, col in db.STATIC_FROM_CC.items()}
    static.update({
        "project_name": run["label"], "country_iso_code": run.get("grid_country"),
        "region": run.get("grid_region"), "on_cloud": "N",
    })
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for s in db.samples(run["id"]):
        row = dict(static)
        for cc, col in db.SAMPLE_FROM_CC.items():
            row[cc] = s[col]
        row["timestamp"] = _local(s["ts"])
        w.writerow([_cell(k, row.get(k)) for k in CSV_HEADER])
    return buf.getvalue()


def command(ref: str | None, fmt: str, out: str | None) -> int:
    if fmt == "sql":
        if ref:
            raise paths.UsageError("--format sql exports the whole database; it takes no label")
        text = "\n".join(db.dump()) + "\n"
    else:
        runs.sweep()
        text = csv_text(runs.find(ref))
    if out:
        with open(out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print(f"Wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0
