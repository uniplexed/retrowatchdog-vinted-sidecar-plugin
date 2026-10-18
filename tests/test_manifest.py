"""What this plugin declares about itself, and why each field is that value.

The claims belong to the process that makes them, so they are pinned here and
not in the app.
"""

import pytest

from app.config import Settings, load_settings
from app.manifest import PROTOCOL_VERSION, SITES, UnknownSite, manifest_payload


def settings_for(*sites: str) -> Settings:
    return Settings(sites=sites or ("uk",), port=0, catalog_ids=(), per_page=None)


def a_source(site: str = "uk") -> dict:
    return manifest_payload(settings_for(site))["sources"][0]


def test_manifest_declares_protocol_3_and_one_source_per_site():
    manifest = manifest_payload(load_settings({}))
    assert manifest["protocol"] == 3
    assert manifest["plugin"]["name"] == "vinted"
    assert [s["id"] for s in manifest["sources"]] == ["vinted_uk", "vinted_fr", "vinted_de", "vinted_es", "vinted_ie"]


def test_only_the_configured_sites_are_declared():
    assert [s["id"] for s in manifest_payload(settings_for("fr", "uk"))["sources"]] == ["vinted_fr", "vinted_uk"]


def test_vinted_quotes_asking_prices_and_nothing_else():
    # The binding honesty rule for this source: what a private seller ASKS is
    # not what anything sold for, so exactly one role may be declared.
    # `reference` would let a scraped, unfiltered sample become the baseline
    # every other source is judged against.
    source = a_source()
    assert source["kindRoles"] == {"active_listing": "buy_listing"}
    assert source["kindLabels"] == {"active_listing": "Vinted UK asking price"}


def test_vinted_reaches_as_far_as_any_marketplace_and_guesses_no_region():
    source = a_source()
    assert source["reach"] == "global"
    assert source["defaultRegion"] is None
    assert source["expectedCurrencies"] == ["GBP"]
    assert source["country"] == "GB"
    assert source["kind"] == "live"


def test_the_manifest_says_it_is_an_unofficial_scraper():
    # The caveat renders under the source header in the app; a source read by
    # scraping has to say so where its prices are shown.
    caveat = a_source()["caveat"]
    assert "unofficial" in caveat.lower()
    # the terms are where a user reads the source's prices, not only in a README
    assert "forbid scraping" in caveat
    assert "https://www.vinted.co.uk/terms_and_conditions" in caveat


def test_no_secrets_are_required():
    assert manifest_payload(load_settings({})).get("requiredSecrets", []) == []


def test_the_site_decides_the_country_the_currency_and_the_heading():
    """Each site declares its own country: vinted.fr does not call itself British.

    A manifest fixed to GB/GBP would not fail loudly — the app would accept the
    source and then rank EUR amounts as pounds, logging one warning per fetch.
    """
    french = a_source("fr")
    assert french["country"] == "FR"
    assert french["expectedCurrencies"] == ["EUR"]
    assert french["label"] == "Vinted France"
    assert french["kindLabels"] == {"active_listing": "Vinted France asking price"}
    assert "Vinted France is read by an unofficial community scraper" in french["caveat"]


def test_an_unknown_site_is_refused_rather_than_guessed():
    with pytest.raises(UnknownSite) as caught:
        manifest_payload(settings_for("uk", "xx"))
    # The message names the variable to change and what it may be set to,
    # because the only person who can fix it is reading the log.
    assert "VINTED_SITES" in str(caught.value)
    assert "xx" in str(caught.value)
    assert "uk, fr, de, es, ie" in str(caught.value)


def test_every_declared_site_names_a_country_the_app_has_a_market_in():
    # COUNTRY_CODES in the app repository, packages/shared/src/index.ts. A
    # site declaring a country
    # the app does not know is rejected by validateManifest, so it would import
    # as an error a user could do nothing about.
    app_countries = {"GB", "ES", "IE", "DE", "FR", "US"}
    assert {site.country for site in SITES.values()} <= app_countries
    # And each of them is distinct: two sites claiming one country would be two
    # sources the collection cannot tell apart when valuing a copy.
    assert len({site.country for site in SITES.values()}) == len(SITES)


def test_labels_every_kind_it_gives_a_role():
    for source in manifest_payload(load_settings({}))["sources"]:
        assert sorted(source["kindLabels"]) == sorted(source["kindRoles"])


def test_the_protocol_version_is_the_one_constant_everything_reads():
    # mapping.py and server.py re-export rather than restate it: one protocol
    # with two version constants is a protocol that can disagree with itself.
    from app import mapping, server

    assert mapping.PROTOCOL_VERSION is PROTOCOL_VERSION
    assert server.PROTOCOL_VERSION is PROTOCOL_VERSION
