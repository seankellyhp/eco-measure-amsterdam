"""The report: one code path for live and finished runs."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from . import sections


def num(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0.0)
    except ValueError:
        return 0.0


def txt(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip() or "n/a"


def hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def last_row(csv_path: Path) -> tuple[dict[str, str], int] | None:
    """The last row of the last run_id, and how many rows that run has.

    Rows are cumulative from tracker start, so the last one is the run's total.
    """
    try:
        with open(csv_path, newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return None
    if not rows:
        return None
    last_run = rows[-1].get("run_id")
    run_rows = [r for r in rows if r.get("run_id") == last_run]
    return run_rows[-1], len(run_rows)


def figures(rundir: Path) -> dict | None:
    """A run's machine figures as data (kWh, kg, s, W), or None if no row yet."""
    found = last_row(Path(rundir) / "emissions.csv")
    if found is None:
        return None
    r, samples = found
    return {
        "row": r,
        "samples": samples,
        "run_id": r.get("run_id"),
        "timestamp": r.get("timestamp"),
        "duration": num(r, "duration"),
        "energy": num(r, "energy_consumed"),
        "emissions": num(r, "emissions"),
        "emissions_rate": num(r, "emissions_rate"),
        "cpu_energy": num(r, "cpu_energy"),
        "gpu_energy": num(r, "gpu_energy"),
        "ram_energy": num(r, "ram_energy"),
        "cpu_power": num(r, "cpu_power"),
        "gpu_power": num(r, "gpu_power"),
        "ram_power": num(r, "ram_power"),
    }


def _as_of(timestamp: str | None) -> str:
    try:
        return datetime.fromisoformat(timestamp).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return datetime.now().strftime("%H:%M:%S")


def render(label: str, rundir: Path, live: bool) -> list[str] | None:
    """The full report as lines, or None if there is no measurement yet."""
    f = figures(rundir)
    if f is None:
        return None
    r = f["row"]
    energy = f["energy"]
    cpu_e, gpu_e, ram_e = f["cpu_energy"], f["gpu_energy"], f["ram_energy"]

    def share(part: float) -> str:
        return f"{part / energy * 100:5.1f}%" if energy > 0 else "    -"

    suffix = f"  [LIVE - as of {_as_of(f['timestamp'])}; final after carbon end]" if live else ""
    out = [
        f"CodeCarbon report - '{label}'" + suffix,
        f"  samples: {f['samples']}   run_id: {f['run_id']}",
        "",
        f"  Compute time      {hms(f['duration'])}  ({f['duration']:,.0f} s)",
        f"  Energy            {energy * 1000:,.3f} Wh   ({energy:.6f} kWh)",
        f"  Emissions         {f['emissions'] * 1000:,.3f} g CO2e   ({f['emissions']:.6f} kg)",
        f"  Emissions rate    {f['emissions_rate'] * 3600 * 1000:,.3f} g CO2e/h",
        "",
        "  Breakdown           energy        share     last sampled power",
        f"    CPU           {cpu_e * 1000:9,.3f} Wh   {share(cpu_e)}   {f['cpu_power']:8,.2f} W",
        f"    GPU           {gpu_e * 1000:9,.3f} Wh   {share(gpu_e)}   {f['gpu_power']:8,.2f} W",
        f"    RAM           {ram_e * 1000:9,.3f} Wh   {share(ram_e)}   {f['ram_power']:8,.2f} W",
        "",
        "  Hardware",
        f"    CPU           {txt(r, 'cpu_model')}  ({txt(r, 'cpu_count')} threads)",
        f"    GPU           {txt(r, 'gpu_model')}  ({txt(r, 'gpu_count')})",
        f"    RAM           {num(r, 'ram_total_size'):.1f} GB",
        "",
    ]
    usage = sections.usage_sections(rundir)
    return out + usage + sections.footer(usage)
