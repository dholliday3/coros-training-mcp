"""Region default heuristics for the setup wizard.

COROS has three API hosts: EU, US, Asia. Picking the right one up front avoids
a failed-login round trip for most users, but we always let them override.
"""
from __future__ import annotations

import time
from typing import Literal

Region = Literal["eu", "us", "asia"]
REGIONS: tuple[Region, ...] = ("eu", "us", "asia")

REGION_LABELS = {
    "eu": "EU  (teameuapi.coros.com)",
    "us": "US  (teamapi.coros.com)",
    "asia": "Asia (teamcnapi.coros.com)",
}


def default_region() -> Region:
    """Best-guess region from the machine's local timezone.

    The IANA timezone name is prefixed with the continent/region the machine
    thinks it's in. We map those continents to COROS regions. Unknown or
    missing timezone info falls back to ``eu`` (matches the upstream default).
    """
    tz_name = time.tzname[0] if time.tzname else ""
    # First try the IANA path if available; `time.tzname` is often abbreviated.
    try:
        import zoneinfo  # stdlib on 3.9+
        from pathlib import Path

        link = Path("/etc/localtime")
        if link.is_symlink():
            target = str(link.readlink())
            # Path usually ends with e.g. ".../zoneinfo/America/Los_Angeles".
            marker = "zoneinfo/"
            if marker in target:
                tz_name = target.split(marker, 1)[1]
    except Exception:
        pass

    prefix = tz_name.split("/", 1)[0].lower()
    if prefix in ("america", "us", "canada", "mexico"):
        return "us"
    if prefix in ("asia", "pacific", "australia"):
        return "asia"
    return "eu"
