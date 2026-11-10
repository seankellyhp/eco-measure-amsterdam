"""Which electricity grid this machine is on - decided once, at carbon start.

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

`resolve()` returns (ISO3, region or "", description).
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

TIMEOUT = float(os.environ.get("CARBON_GEO_TIMEOUT") or "4")
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


def _supported() -> set[str] | None:
    """ISO-3 codes codecarbon has grid data for, or None if its data file is not found.

    Read from the file directly: importing codecarbon here would slow every start.
    """
    from importlib.util import find_spec

    try:
        spec = find_spec("codecarbon")
        for folder in spec.submodule_search_locations or []:
            path = Path(folder) / "data" / "private_infra" / "global_energy_mix.json"
            if path.is_file():
                return set(json.loads(path.read_text(encoding="utf-8")))
    except (AttributeError, ImportError, OSError, ValueError):
        pass
    return None


def _checked_country(code: str) -> str:
    """CARBON_COUNTRY as an ISO-3 code codecarbon knows, else a usage error.

    codecarbon accepts any string and quietly uses the world average for one it
    does not know, so a typo or a two-letter code would give the wrong CO2e.
    """
    from .paths import UsageError

    iso = code
    if len(code) == 2 and code.isalpha():
        try:
            import pycountry

            found = pycountry.countries.get(alpha_2=code)
        except Exception:
            found = None
        if found is not None:
            iso = found.alpha_3
    known = _supported()
    if len(iso) != 3 or not iso.isalpha():
        raise UsageError(
            f"CARBON_COUNTRY must be a three-letter ISO country code such as NLD, DEU, GBR or USA, not {code!r}."
        )
    if known is not None and iso not in known:
        raise UsageError(
            f"CARBON_COUNTRY={code!r}: codecarbon has no electricity grid data for that code. "
            "Use a three-letter ISO country code such as NLD, DEU, GBR or USA."
        )
    return iso


def resolve(cache: Path | None = None) -> tuple[str, str, str]:
    """(ISO-3 country, region or '', description of how it was chosen)."""
    explicit = os.environ.get("CARBON_COUNTRY", "").strip().upper()
    if explicit:
        iso = _checked_country(explicit)
        region = os.environ.get("CARBON_REGION", "").strip().lower()
        note = "" if iso == explicit else f" ({explicit} read as {iso})"
        return iso, region, "set by CARBON_COUNTRY" + note

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
        return iso, region, f"{where} - detected from your IP address via {name}"

    if cache and cache.is_file():
        try:
            d = json.loads(cache.read_text())
            return (d["country"], d.get("region") or "",
                    f"LOCATION LOOKUP FAILED - using the last detected location "
                    f"({d.get('name') or d['country']}, {d.get('date')}); set CARBON_COUNTRY to override")
        except (OSError, ValueError, KeyError):
            pass

    return (FALLBACK, "", f"LOCATION LOOKUP FAILED - assuming {FALLBACK}; "
            f"set CARBON_COUNTRY to your country's ISO-3 code")
