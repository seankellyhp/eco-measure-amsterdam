"""Which electricity grid this machine is on - decided once, at carbon_start.

Same method as codecarbon's online mode (codecarbon.external.geography,
GeoMetadata.from_geo_js): look the public IP up at get.geojs.io, and at
ipinfo.io if that fails. The differences are deliberate:

* codecarbon gives each service 0.5 s and, if both fail, silently assumes
  Canada/Quebec - a near-zero-carbon hydro grid - so a slow network quietly
  turns a real footprint into almost nothing. Here each service gets a few
  seconds, a failure falls back to the last location that was detected on
  this machine, and the source of the answer is always printed.
* The lookup runs once, here; the monitor itself then runs offline with the
  result, so the grid used is recorded in the run dir and never changes
  mid-run.

CARBON_COUNTRY (ISO-3) skips the lookup entirely - no network request is made.
CARBON_REGION optionally adds a region (used by codecarbon for USA, CAN, CHN
and the Nordic countries).

Prints one tab-separated line:  <ISO3> <TAB> <region or -> <TAB> <description>
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

TIMEOUT = float(os.environ.get("CARBON_GEO_TIMEOUT", "4"))
PRIMARY = "https://get.geojs.io/v1/ip/geo.json"  # codecarbon's geo_js_url
BACKUP = "https://ipinfo.io/json"  # codecarbon's backup
FALLBACK = "NLD"


def _from_geojs() -> tuple[str, str, str]:
    import requests

    r = requests.get(PRIMARY, timeout=TIMEOUT).json()
    return r["country_code3"].upper(), (r.get("region") or "").lower(), r.get("country") or ""


def _from_ipinfo() -> tuple[str, str, str]:
    import pycountry
    import requests

    r = requests.get(BACKUP, timeout=TIMEOUT).json()
    c = pycountry.countries.get(alpha_2=r.get("country"))
    if c is None:
        raise ValueError(f"unknown country code {r.get('country')!r}")
    return c.alpha_3, (r.get("region") or "").lower(), c.name


def main() -> None:
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    explicit = os.environ.get("CARBON_COUNTRY", "").strip().upper()
    if explicit:
        region = os.environ.get("CARBON_REGION", "").strip().lower()
        print(f"{explicit}\t{region or '-'}\tset by CARBON_COUNTRY")
        return

    for name, fn in (("get.geojs.io", _from_geojs), ("ipinfo.io", _from_ipinfo)):
        try:
            iso, region, country = fn()
            if len(iso) != 3:
                raise ValueError(f"bad country code {iso!r}")
        except Exception:
            continue
        if cache:
            try:
                cache.write_text(json.dumps(
                    {"country": iso, "region": region, "name": country,
                     "source": name, "date": date.today().isoformat()}))
            except OSError:
                pass
        where = f"{country}, {region}" if region else country
        print(f"{iso}\t{region or '-'}\t{where} - detected from your IP address via {name}")
        return

    if cache and cache.is_file():
        try:
            d = json.loads(cache.read_text())
            print(f"{d['country']}\t{d.get('region') or '-'}\t"
                  f"LOCATION LOOKUP FAILED - using the last detected location "
                  f"({d.get('name') or d['country']}, {d.get('date')}); set CARBON_COUNTRY to override")
            return
        except (OSError, ValueError, KeyError):
            pass

    print(f"{FALLBACK}\t-\tLOCATION LOOKUP FAILED - assuming {FALLBACK}; "
          f"set CARBON_COUNTRY to your country's ISO-3 code")


if __name__ == "__main__":
    main()
