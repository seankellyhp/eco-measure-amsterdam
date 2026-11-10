from __future__ import annotations

import csv
import sys

import sections


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


def main() -> int:
    # power_mode (argv[4]) is still accepted so the call signature is stable.
    path, label, running = sys.argv[1:4]
    rundir = sys.argv[5] if len(sys.argv) > 5 else None

    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"emissions.csv for '{label}' has no rows yet.", file=sys.stderr)
        return 1

    last_run = rows[-1].get("run_id")
    run_rows = [r for r in rows if r.get("run_id") == last_run]
    r = run_rows[-1]

    duration = num(r, "duration")
    energy = num(r, "energy_consumed")
    emissions = num(r, "emissions")
    cpu_e, gpu_e, ram_e = num(r, "cpu_energy"), num(r, "gpu_energy"), num(r, "ram_energy")

    def share(part: float) -> str:
        return f"{part / energy * 100:5.1f}%" if energy > 0 else "    -"

    print(f"CodeCarbon report - '{label}'" + ("  [MONITOR STILL RUNNING]" if running == "yes" else ""))
    print(f"  samples: {len(run_rows)}   run_id: {last_run}")
    print()
    print(f"  Compute time      {hms(duration)}  ({duration:,.0f} s)")
    print(f"  Energy            {energy * 1000:,.3f} Wh   ({energy:.6f} kWh)")
    print(f"  Emissions         {emissions * 1000:,.3f} g CO2e   ({emissions:.6f} kg)")
    print(f"  Emissions rate    {num(r, 'emissions_rate') * 3600 * 1000:,.3f} g CO2e/h")
    print()
    print("  Breakdown           energy        share     last sampled power")
    print(f"    CPU           {cpu_e * 1000:9,.3f} Wh   {share(cpu_e)}   {num(r, 'cpu_power'):8,.2f} W")
    print(f"    GPU           {gpu_e * 1000:9,.3f} Wh   {share(gpu_e)}   {num(r, 'gpu_power'):8,.2f} W")
    print(f"    RAM           {ram_e * 1000:9,.3f} Wh   {share(ram_e)}   {num(r, 'ram_power'):8,.2f} W")
    print()
    print("  Hardware")
    print(f"    CPU           {txt(r, 'cpu_model')}  ({txt(r, 'cpu_count')} threads)")
    print(f"    GPU           {txt(r, 'gpu_model')}  ({txt(r, 'gpu_count')})")
    print(f"    RAM           {num(r, 'ram_total_size'):.1f} GB")
    print()
    usage = sections.usage_sections(rundir)
    for line in usage + sections.footer(usage):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
