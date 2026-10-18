"""One Vinted item to one raw protocol listing.

The sidecar fetches and never classifies: platform, region, completeness and
grade are read by the app's one shared classifier, since two sources
classifying separately would break cross-source comparison silently. This
module imports nothing from `vinted_scraper`, so it tests without the package.
Field provenance is in ../README.md; read it before adding a field.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

#: The protocol version, re-exported so there is only one constant.
from .manifest import PROTOCOL_VERSION  # noqa: F401  (imported for re-export)

#: Private sellers' asking prices: the only kind Vinted can honestly send.
PRICE_KIND = "active_listing"

#: ISO 4217 alpha. An unknown code falls back to rate 1 app-side, and the
#: frozen USD amount would be wrong permanently.
_ISO_4217 = re.compile(r"^[A-Z]{3}$")

#: The only link shape the app accepts; it refuses the row otherwise.
_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)


class ItemMappingError(ValueError):
    """This item cannot be expressed as a protocol listing, and why.

    Raised rather than repaired: a patched listing would sit beside real
    evidence with nothing saying it was a guess.
    """


def map_item(item: Any, base_url: str) -> Dict[str, Any]:
    """Map one package item to one raw listing, or refuse it.

    `base_url` only absolutises a site-relative path; it is never read as a region.
    """
    source_product_id = _text(getattr(item, "id", None))
    if source_product_id is None:
        raise ItemMappingError("item has no id, so the app could not key a mapping to it")

    title = _text(getattr(item, "title", None), strip=False)
    if title is None:
        raise ItemMappingError(f"item {source_product_id} has no title")

    listing: Dict[str, Any] = {
        "sourceProductId": source_product_id,
        # unedited: the app's matcher is tuned on real seller text
        "title": title,
        "prices": [_price(item, source_product_id)],
        "url": _url(item, base_url),
    }

    # the source's own condition WORDS (a cosmetic grade), never our reading of them
    condition_text = _text(getattr(item, "status", None))
    if condition_text is not None:
        listing["conditionText"] = condition_text

    return listing


def _price(item: Any, source_product_id: str) -> Dict[str, Any]:
    """The item's asking price, exactly as quoted: never converted, never
    fee-inclusive (that would compare Vinted-plus-fees against eBay-without).
    """
    amount = getattr(item, "price", None)
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ItemMappingError(
            f"item {source_product_id} price {amount!r} is not a number"
        )
    amount = float(amount)
    if not math.isfinite(amount) or amount < 0:
        raise ItemMappingError(
            f"item {source_product_id} price {amount!r} is not a finite, non-negative amount"
        )

    currency = getattr(item, "currency", None)
    if not isinstance(currency, str):
        raise ItemMappingError(f"item {source_product_id} has no currency")
    currency = currency.strip().upper()
    if not _ISO_4217.match(currency):
        raise ItemMappingError(
            f"item {source_product_id} currency {currency!r} is not an ISO 4217 code"
        )

    return {"kind": PRICE_KIND, "amount": amount, "currency": currency}


def _url(item: Any, base_url: str) -> Optional[str]:
    """The listing's page as an absolute http(s) link, or None.

    Tries the item's `url`, then its site-relative `path` joined to the site.
    Anything else is skipped, not repaired: the app refuses the whole row for a
    bad link, and a listing is worth more than a link.
    """
    site_host = urlparse(base_url).netloc.lower()
    for candidate in (_text(getattr(item, "url", None)), _text(getattr(item, "path", None))):
        if candidate is None:
            continue
        if _HTTP_URL.match(candidate):
            # the listing's own site only: a link anywhere else is not this listing
            if urlparse(candidate).netloc.lower() == site_host:
                return candidate
            continue
        # site-relative only: joining anything else would invent a link
        if candidate.startswith("/"):
            return urljoin(base_url, candidate)
    return None


def _text(value: Any, strip: bool = True) -> Optional[str]:
    """A non-empty string, or None. Integers (the package's item ids) become their decimal form."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        return None
    if not value.strip():
        return None
    return value.strip() if strip else value
