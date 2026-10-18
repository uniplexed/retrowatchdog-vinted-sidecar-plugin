"""This deployment's settings, read once from the environment.

Nothing here is a secret or belongs to the app: a sidecar gets no database or
app credential. Pacing and retries are the app's.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

#: Every site this plugin knows (manifest.SITES), all served by default: a
#: declared source costs nothing until its market is switched on in the app.
DEFAULT_SITES = ("uk", "fr", "de", "es", "ie")

#: "Video games & consoles", the same id on every known site (verified
#: 2026-10-18). Without it a title search also returns books and films.
DEFAULT_CATALOG_IDS = ("3002",)

DEFAULT_PORT = 8000


@dataclass(frozen=True)
class Settings:
    #: Site keys (manifest.SITES); each one is the source `vinted_<key>`.
    sites: Tuple[str, ...]
    port: int
    #: Vinted catalogue ids to narrow searches to. A wrong id returns nothing
    #: silently, so only verified ones belong here.
    catalog_ids: Tuple[str, ...]
    #: Page size to ask for, unset by default: the parameter is unverified.
    per_page: Optional[int]


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    values = os.environ if env is None else env
    return Settings(
        sites=tuple(s.lower() for s in _split(values.get("VINTED_SITES", ""))) or DEFAULT_SITES,
        # a blank PORT means unset; int("") would raise before the server binds
        port=_optional_int(values.get("PORT", "")) or DEFAULT_PORT,
        catalog_ids=_split(values.get("VINTED_CATALOG_IDS", "")) or DEFAULT_CATALOG_IDS,
        per_page=_optional_int(values.get("VINTED_PER_PAGE", "")),
    )


def _split(value: str) -> Tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _optional_int(value: str) -> Optional[int]:
    value = value.strip()
    return int(value) if value else None
