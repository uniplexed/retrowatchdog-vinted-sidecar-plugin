"""What one Vinted item is allowed to become on the wire.

Every item in this file is HAND-WRITTEN. Nothing here was captured from
Vinted: this repository makes no live call to Vinted from any test, script or
build step, so the stand-in below is built from the fields the package's own
model source declares (`vinted_scraper.models._item.VintedItem`: id, title,
price, currency, url, path, status, brand_title, size_title, ...) and not from
an observed response. Where the package's behaviour could only be settled by a
live call, the service README records it as unverified rather than guessing
here.

That is a real limitation and worth naming: these tests pin OUR mapping, not
Vinted's payload. If the package ever renames a field, this suite stays green
and the sidecar returns nothing — which is why the service README makes
bumping the pinned version the explicit maintenance action.
"""

from types import SimpleNamespace

import pytest

from app.mapping import ItemMappingError, PRICE_KIND, map_item

SITE = "https://www.vinted.co.uk"


def vinted_item(**fields):
    """A stand-in for the package's VintedItem, carrying only what is passed.

    An omitted keyword is an ABSENT attribute, not a None one, so a test can
    say "the package did not populate this field" the way the package does:
    every field of the real model is Optional and several are only filled in
    from keys the source happened to send.
    """
    return SimpleNamespace(**fields)


def a_full_item(**overrides):
    fields = {
        "id": 4210998877,
        "title": "Legend of Zelda Ocarina of Time N64 boxed with manual PAL",
        "price": 42.5,
        "currency": "GBP",
        "url": "https://www.vinted.co.uk/items/4210998877-zelda-ocarina-of-time",
        "path": "/items/4210998877-zelda-ocarina-of-time",
        "status": "Very good",
    }
    fields.update(overrides)
    return vinted_item(**fields)


def test_maps_a_normal_listing_to_the_protocol_shape():
    listing = map_item(a_full_item(), SITE)

    assert listing == {
        "sourceProductId": "4210998877",
        "title": "Legend of Zelda Ocarina of Time N64 boxed with manual PAL",
        "prices": [{"kind": PRICE_KIND, "amount": 42.5, "currency": "GBP"}],
        "url": "https://www.vinted.co.uk/items/4210998877-zelda-ocarina-of-time",
        "conditionText": "Very good",
    }


def test_the_only_price_kind_is_an_asking_price():
    """Vinted is private sellers asking for money, never a shop's quote."""
    assert PRICE_KIND == "active_listing"


def test_the_title_is_passed_through_unedited():
    raw = "  RARE!! Pokemon Red Gameboy PAL - cart only, tested  "
    listing = map_item(a_full_item(title=raw), SITE)
    assert listing["title"] == raw


def test_a_missing_optional_field_is_omitted_rather_than_invented():
    """The source did not say it, so the listing does not claim it."""
    item = vinted_item(id=7, title="Super Mario 64 N64", price=12.0, currency="GBP")

    listing = map_item(item, SITE)

    assert listing["url"] is None
    assert "conditionText" not in listing


def test_a_url_is_rebuilt_from_the_item_path_when_the_package_left_it_empty():
    item = a_full_item(url=None)
    listing = map_item(item, SITE)
    assert listing["url"] == "https://www.vinted.co.uk/items/4210998877-zelda-ocarina-of-time"


def test_a_site_relative_link_is_made_absolute_against_this_site():
    """Whichever field carried it: the app takes absolute http(s) links only."""
    listing = map_item(a_full_item(url="/items/4210998877-zelda", path=None), SITE)
    assert listing["url"] == "https://www.vinted.co.uk/items/4210998877-zelda"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "not a url", "mailto:seller@example.test"])
def test_a_link_the_app_would_refuse_is_omitted_rather_than_sent(url):
    """A listing is worth more than a link.

    The app requires an absolute http(s) URL and drops the whole ROW when a
    present `url` is not one — it renders that link and vouches for it by
    doing so. Sending a link this sidecar cannot vouch for would therefore
    cost the listing, so a link that would not survive is left out and the
    listing travels without one, which the protocol allows.
    """
    listing = map_item(a_full_item(url=url, path=None), SITE)

    assert listing["url"] is None
    assert listing["sourceProductId"] == "4210998877"


def test_nothing_the_app_classifies_is_ever_sent():
    """The sidecar fetches, the app interprets — enforced, not requested.

    The item carries plenty a careless mapper could read as a platform, a
    region or a condition tier. None of it may leave: only the protocol's own
    keys appear, and the source's own condition WORDS travel as conditionText
    for the app to read.
    """
    item = a_full_item(
        brand_title="Nintendo",
        size_title="N64",
        is_visible=True,
        service_fee=1.35,
        total_item_price=43.85,
        description="PAL cartridge, complete in box, mint",
    )

    listing = map_item(item, SITE)

    assert set(listing) == {"sourceProductId", "title", "prices", "url", "conditionText"}


@pytest.mark.parametrize(
    "price",
    ["42.50", None, float("nan"), float("inf"), -1.0, True],
    ids=["string", "absent", "nan", "infinite", "negative", "boolean"],
)
def test_rejects_a_price_the_protocol_could_not_carry(price):
    """A price shape we cannot vouch for costs the whole listing.

    Not the price alone: a listing emitted with its price dropped looks like a
    listing that simply has none, and the app would store that silence as
    evidence. Refusing the row makes the mapping bug visible in one log line.
    """
    with pytest.raises(ItemMappingError):
        map_item(a_full_item(price=price), SITE)


@pytest.mark.parametrize(
    "currency",
    ["euro", "", None, "£", "GBPX"],
    ids=["word", "empty", "absent", "symbol", "too-long"],
)
def test_rejects_a_currency_that_is_not_an_iso_4217_code(currency):
    """The app converts by looking the code up and falls back to rate 1.

    An unrecognised code would file a EUR listing as dollars, permanently:
    the USD twin is frozen at write time and never re-derived. Shape-checking
    here is cheaper than that.
    """
    with pytest.raises(ItemMappingError):
        map_item(a_full_item(currency=currency), SITE)


def test_normalises_the_case_of_an_iso_code():
    """Upper-casing a code is not interpretation; inventing one would be."""
    listing = map_item(a_full_item(currency="gbp"), SITE)
    assert listing["prices"][0]["currency"] == "GBP"


@pytest.mark.parametrize("missing", ["id", "title"], ids=["id", "title"])
def test_rejects_an_item_the_app_could_not_key_or_read(missing):
    item = a_full_item(**{missing: None})
    with pytest.raises(ItemMappingError):
        map_item(item, SITE)
