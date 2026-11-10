"""The report: one code path for live and finished runs."""

from __future__ import annotations

from datetime import datetime

from . import db, sections


def hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _txt(value) -> str:
    """A hardware fact as CodeCarbon's CSV showed it: whole counts without '.0'."""
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() or "n/a"


def figures(run_id: int) -> dict | None:
    """A run's machine figures as data (kWh, kg, s, W), or None if no sample yet.

    Samples are cumulative from tracker start, so the last one is the run's total.
    """
    found = db.last_sample(run_id)
    if found is None:
        return None
    r, samples = found
    return {
        "samples": samples,
        "timestamp": r["ts"],
        "duration": r["duration_s"],
        "energy": r["energy_kwh"],
        "emissions": r["emissions_kg"],
        "emissions_rate": r["emissions_rate_kg_s"],
        "cpu_energy": r["cpu_energy_kwh"],
        "gpu_energy": r["gpu_energy_kwh"],
        "ram_energy": r["ram_energy_kwh"],
        "cpu_power": r["cpu_power_w"],
        "gpu_power": r["gpu_power_w"],
        "ram_power": r["ram_power_w"],
    }


def _as_of(timestamp: str | None) -> str:
    try:
        return datetime.fromisoformat(timestamp).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return datetime.now().strftime("%H:%M:%S")


def render(run: dict, live: bool) -> list[str] | None:
    """The full report as lines, or None if there is no measurement yet."""
    f = figures(run["id"])
    if f is None:
        return None
    label = run["label"]
    energy = f["energy"]
    cpu_e, gpu_e, ram_e = f["cpu_energy"], f["gpu_energy"], f["ram_energy"]

    def share(part: float) -> str:
        return f"{part / energy * 100:5.1f}%" if energy > 0 else "    -"

    suffix = f"  [LIVE - as of {_as_of(f['timestamp'])}; final after carbon end]" if live else ""
    out = [
        f"CodeCarbon report - '{label}'" + suffix,
        f"  samples: {f['samples']}   run_id: {_txt(run.get('codecarbon_run_id'))}",
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
        f"    CPU           {_txt(run.get('cpu_model'))}  ({_txt(run.get('cpu_count'))} threads)",
        f"    GPU           {_txt(run.get('gpu_model'))}  ({_txt(run.get('gpu_count'))})",
        f"    RAM           {run.get('ram_total_gb') or 0.0:.1f} GB",
        "",
    ]
    usage = sections.usage_sections(run)
    return out + usage + sections.footer(usage)
