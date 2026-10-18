"""The fetch: ask the package, map what comes back, drop what will not map.

The platform hint is accepted and NOT used: per-platform catalogue ids are
unverified, and a wrong id returns an empty set that looks like "Vinted has
none". Every search is narrowed to VINTED_CATALOG_IDS (3002, video games &
consoles, by default).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .config import Settings
from .mapping import ItemMappingError, map_item
from .scrapers import get_scraper

log = logging.getLogger(__name__)


def search_listings(
    settings: Settings, base_url: str, query: str, platform: Optional[str] = None
) -> List[Dict[str, Any]]:
    if platform:
        log.debug("platform hint %s ignored: catalogue ids are unverified", platform)

    params: Dict[str, Any] = {"search_text": query}
    if settings.catalog_ids:
        # the scraper's key, comma-separated; the web URL's "catalog[]" is
        # ignored by the API, which then searches every category
        params["attribute_ids[catalog]"] = ",".join(settings.catalog_ids)
    if settings.per_page is not None:
        params["per_page"] = settings.per_page

    items = get_scraper(base_url).search(params)

    listings: List[Dict[str, Any]] = []
    for item in items:
        try:
            listings.append(map_item(item, base_url))
        except ItemMappingError as error:
            # one bad item costs only itself; logged so the maintainer sees it
            log.warning("dropping an item: %s", error)
    return listings
