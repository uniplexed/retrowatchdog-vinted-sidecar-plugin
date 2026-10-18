"""The fetch: what is asked of the source, and what survives the mapping.

No network and no package. `get_scraper` takes a factory precisely so a stub
can stand in for `vinted_scraper`, and this file is what that seam is for —
every scraper below is a hand-written object recording the params it was
handed. Nothing here was captured from Vinted; the items are the same
hand-written stand-ins `test_mapping.py` uses, for the same reason.

What is pinned here is the promise the protocol makes on this side of the
wire: one unmappable item costs that item and nothing else. Turn that `except`
into a propagation and the server answers 502 for the whole query — the app
would count a failure, open its breaker, and report an outage of a source that
had answered with one odd row among many.
"""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.scrapers import get_scraper, reset_scrapers
from app.search import search_listings

SITE = "https://www.vinted.co.uk"


def settings(**overrides):
    fields = {
        "sites": ("uk",),
        "port": 0,
        "catalog_ids": (),
        "per_page": None,
    }
    fields.update(overrides)
    return Settings(**fields)


class StubScraper:
    """Records the params it was asked for and answers a fixed list."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    def search(self, params):
        self.calls.append(params)
        return self.items


def item(id_, title, price=12.0, currency="GBP"):
    return SimpleNamespace(
        id=id_, title=title, price=price, currency=currency,
        url=f"{SITE}/items/{id_}", path=f"/items/{id_}", status="Very good",
    )


@pytest.fixture(autouse=True)
def clean_scraper_cache():
    reset_scrapers()
    yield
    reset_scrapers()


def install(scraper, base_url=SITE):
    """Seed the process-wide cache, so search_listings finds the stub."""
    get_scraper(base_url, factory=lambda _: scraper)
    return scraper


def test_maps_every_item_the_source_returned():
    install(StubScraper([item(1, "Pilotwings 64"), item(2, "Super Mario 64 N64")]))

    listings = search_listings(settings(), SITE, "mario")

    assert [l["sourceProductId"] for l in listings] == ["1", "2"]


def test_one_unmappable_item_costs_that_item_and_nothing_else():
    """The whole reason the mapping raises instead of repairing.

    A search that answered a hundred rows must not become a failure of the
    source because one of them quoted its price in a way the protocol cannot
    carry. The app drops rows too, and for the same reason — but it can only
    drop the ones that reach it.
    """
    broken = SimpleNamespace(id=9, title="Zelda Ocarina of Time N64", price="42.50", currency="GBP")
    install(StubScraper([item(1, "Pilotwings 64"), broken, item(2, "F-Zero SNES")]))

    listings = search_listings(settings(), SITE, "anything")

    assert [l["sourceProductId"] for l in listings] == ["1", "2"]


def test_an_empty_answer_is_an_answer():
    install(StubScraper([]))
    assert search_listings(settings(), SITE, "nothing here") == []


def test_asks_for_the_search_text_and_nothing_else_by_default():
    """Keyword-only until an operator has VERIFIED the catalogue ids.

    A guessed catalogue id narrows a search to nothing and looks exactly like
    "Vinted has none of these", which is the one failure this whole posture
    exists to avoid.
    """
    scraper = install(StubScraper([]))

    search_listings(settings(), SITE, "zelda", platform="n64")

    assert scraper.calls == [{"search_text": "zelda"}]


def test_passes_the_operator_s_catalogue_ids_and_page_size_when_set():
    scraper = install(StubScraper([]))

    search_listings(settings(catalog_ids=("2309", "1131"), per_page=48), SITE, "zelda")

    # the scraper's own key, comma-separated: the web URL's "catalog[]" is
    # silently ignored by the API and searches every category
    assert scraper.calls == [{"search_text": "zelda", "attribute_ids[catalog]": "2309,1131", "per_page": 48}]


def test_the_scraper_is_built_once_and_then_kept():
    """A fresh instance per request would bootstrap a cookie per request.

    That is both slower and a far louder pattern at a source that already
    dislikes being scraped — which is why the lifetime is a cache with a lock
    rather than a constructor call in the request path.
    """
    built = []

    def factory(base_url):
        built.append(base_url)
        return StubScraper([])

    first = get_scraper(SITE, factory=factory)
    second = get_scraper(SITE, factory=factory)

    assert first is second
    assert built == [SITE]


def test_two_sites_never_share_one_scraper():
    """One process serves every site, and each keeps its own session."""
    made = {}

    def factory(base_url):
        made[base_url] = StubScraper([])
        return made[base_url]

    uk = get_scraper(SITE, factory=factory)
    fr = get_scraper("https://www.vinted.fr", factory=factory)

    assert uk is not fr
    assert set(made) == {SITE, "https://www.vinted.fr"}
