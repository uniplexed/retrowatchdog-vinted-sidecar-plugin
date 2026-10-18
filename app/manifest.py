"""What this sidecar declares itself to be: a PROPOSAL the app validates and a
person approves before any price is stored.

- ONE role, `buy_listing`: every Vinted number is an asking price, so it must
  never become the `reference` baseline.
- `global` reach: a seller can post from anywhere.
- No `sellFeeRate`: only read for a `reference` reading, which this lacks.

One process serves every configured site, one source per site
(`vinted_<key>`). The site decides country, currency and label, and an unknown
key is refused: a guessed currency would misprice silently.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, NamedTuple

from .config import Settings

PROTOCOL_VERSION = 3
PLUGIN_NAME = "vinted"
PLUGIN_VERSION = "1.0.0"

#: Vinted's terms: no bots, scraping or data mining without its authorization.
TERMS_URL = "https://www.vinted.co.uk/terms_and_conditions"


class Site(NamedTuple):
    """The facts a Vinted country site fixes, and the app must be told."""

    base_url: str

    #: ISO country code; must be one the app has a market in (COUNTRY_CODES).
    country: str
    #: What that site quotes; the app drops a listing in any other currency.
    currency: str
    #: The heading a user reads above these prices.
    label: str


#: Keyed by the VINTED_SITES key; the source id is `vinted_<key>`. Only sites
#: somebody has actually looked at belong here.
SITES: Mapping[str, Site] = {
    "uk": Site(base_url="https://www.vinted.co.uk", country="GB", currency="GBP", label="Vinted UK"),
    "fr": Site(base_url="https://www.vinted.fr", country="FR", currency="EUR", label="Vinted France"),
    "de": Site(base_url="https://www.vinted.de", country="DE", currency="EUR", label="Vinted Deutschland"),
    "es": Site(base_url="https://www.vinted.es", country="ES", currency="EUR", label="Vinted España"),
    "ie": Site(base_url="https://www.vinted.ie", country="IE", currency="EUR", label="Vinted Ireland"),
}


class UnknownSite(Exception):
    """VINTED_SITES names a site this manifest cannot describe.

    Raised, not defaulted: a guessed currency would misprice silently.
    """


def source_id(key: str) -> str:
    return f"vinted_{key}"


def served_sites(settings: Settings) -> Dict[str, Site]:
    """Source id -> site, for every configured key; an unknown key raises."""
    unknown = [key for key in settings.sites if key not in SITES]
    if unknown:
        raise UnknownSite(
            f"VINTED_SITES names {', '.join(unknown)}, not a Vinted site this sidecar can declare; "
            f"known sites: {', '.join(SITES)}"
        )
    return {source_id(key): SITES[key] for key in settings.sites}


def manifest_payload(settings: Settings) -> Dict[str, Any]:
    return {
        "protocol": PROTOCOL_VERSION,
        "plugin": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION},
        "requiredSecrets": [],
        "sources": [
            {
                "id": sid,
                "kind": "live",
                "label": site.label,
                "family": "vinted",
                "familyLabel": "Vinted",
                "country": site.country,
                "reach": "global",
                # Vinted listings rarely declare a region and the app must not
                # invent one from the site's country.
                "defaultRegion": None,
                "expectedCurrencies": [site.currency],
                "kindRoles": {"active_listing": "buy_listing"},
                # "asking price", not "listing": the wording is the honesty
                "kindLabels": {"active_listing": f"{site.label} asking price"},
                "caveat": (
                    f"{site.label} is read by an unofficial community scraper: asking prices from "
                    "private sellers, best-effort. Vinted's terms forbid scraping without its "
                    f"authorization: {TERMS_URL}"
                ),
            }
            for sid, site in served_sites(settings).items()
        ],
    }
