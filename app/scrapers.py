"""One scraper per site, built on first use and then kept.

Constructing the package's scraper bootstraps a session cookie, and that
bootstrap is per site: a fresh instance per request would mean a cookie fetch
per request, which is both slower and a far louder pattern than the one search
the app actually asked for.

The cache is keyed by site: one process serves every configured country, and
each site keeps its own session, so one site's cookie trouble stays its own.

`vinted_scraper` is imported inside the factory rather than at module import,
so every other module here — and the whole test suite — loads without the
package present. The package is this file's business alone.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

_lock = threading.Lock()
_scrapers: Dict[str, Any] = {}


def get_scraper(base_url: str, factory: Optional[Callable[[str], Any]] = None) -> Any:
    """The scraper for `base_url`, building it once if it does not exist yet.

    The lock is held across construction on purpose. Two requests arriving
    together on a cold container would otherwise each bootstrap a cookie, and
    the second one is pure noise aimed at a source that already dislikes being
    scraped.
    """
    build = factory or _build_vinted_scraper
    with _lock:
        scraper = _scrapers.get(base_url)
        if scraper is None:
            log.info("building a scraper for %s", base_url)
            scraper = build(base_url)
            _scrapers[base_url] = scraper
        return scraper


def reset_scrapers() -> None:
    """Forget every cached scraper. For tests, and for a manual cookie reset."""
    with _lock:
        _scrapers.clear()


def _build_vinted_scraper(base_url: str) -> Any:
    """The package's documented constructor call, and nothing more.

    No user agent is passed and no session cookie is supplied: the package
    ships its own user-agent handling and fetches a session cookie itself, and
    overriding either from here would be guessing at parameters this
    repository cannot verify without a live call to Vinted. If Vinted's
    defences change, the fix is upstream and arrives as a version bump.
    """
    from vinted_scraper import VintedScraper  # imported late: see module docstring

    return VintedScraper(base_url)
