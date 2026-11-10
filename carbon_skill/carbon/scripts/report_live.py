from __future__ import annotations

import re
import sys
from datetime import datetime

import sections


def last(pattern: str, text: str) -> float | None:
    hits = re.findall(pattern, text)
    return float(hits[-1]) if hits else None


def main() -> int:
    # power_mode (argv[4]) is still accepted so the call signature is stable.
    log_path, started_at, label = sys.argv[1:4]
    rundir = sys.argv[5] if len(sys.argv) > 5 else None
    text = open(log_path, errors="replace").read()

    total = last(r"([\d.]+) kWh of electricity .* since the beginning", text)
    if total is None:
        print("No completed measurement in monitor.log yet - wait one sampling interval.", file=sys.stderr)
        return 1

    cpu = last(r"Energy consumed for All CPU\s*:\s*([\d.]+) kWh", text) or 0.0
    gpu = last(r"Energy consumed for all GPUs\s*:\s*([\d.]+) kWh", text) or 0.0
    ram = last(r"Energy consumed for RAM\s*:\s*([\d.]+) kWh", text) or 0.0
    cpu_w = last(r"consumed for CPU with \w+\s*:\s*[\d.]+ kWh, power\s*:\s*([\d.]+) W", text) or 0.0
    gpu_w = last(r"Total GPU Power\s*:\s*([\d.]+)", text) or 0.0
    ram_w = last(r"RAM Power\s*:\s*([\d.]+) W", text) or 0.0

    duration = (datetime.now().astimezone() - datetime.fromisoformat(started_at.strip())).total_seconds()

    def share(part: float) -> str:
        return f"{part / total * 100:5.1f}%" if total > 0 else "    -"

    s = int(round(duration))
    print(f"CodeCarbon report - '{label}'  [LIVE, from monitor.log; totals are final only after carbon_end]")
    print()
    print(f"  Compute time      {s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}  ({duration:,.0f} s)")
    print(f"  Energy            {total * 1000:,.3f} Wh   ({total:.6f} kWh)")
    print("  Emissions         (computed at stop - run carbon_end for CO2e)")
    print()
    print("  Breakdown           energy        share     last sampled power")
    print(f"    CPU           {cpu * 1000:9,.3f} Wh   {share(cpu)}   {cpu_w:8,.2f} W")
    print(f"    GPU           {gpu * 1000:9,.3f} Wh   {share(gpu)}   {gpu_w:8,.2f} W")
    print(f"    RAM           {ram * 1000:9,.3f} Wh   {share(ram)}   {ram_w:8,.2f} W")
    print()
    usage = sections.usage_sections(rundir)
    for line in usage + sections.footer(usage):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
