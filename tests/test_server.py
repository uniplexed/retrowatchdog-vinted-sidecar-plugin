"""The two endpoints, driven over a real socket bound to loopback only.

No network: the server under test is this process, the port is chosen by the
kernel on 127.0.0.1, and the search function is a stub. Nothing here reaches
Vinted, and nothing in this repository ever does.

The stub matters as much as the assertions. `make_handler` takes the search
function as an argument precisely so the HTTP surface can be exercised without
the scraper — which means this test also pins that the surface never imports
`vinted_scraper` to answer a request.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app.config import Settings
from app.mapping import PROTOCOL_VERSION
from app.server import make_handler

SETTINGS = Settings(
    sites=("uk", "fr"),
    port=0,
    catalog_ids=(),
    per_page=None,
)

# Hand-written, not captured: one row in the shape app/mapping.py produces.
A_LISTING = {
    "sourceProductId": "4210998877",
    "title": "Legend of Zelda Ocarina of Time N64 boxed PAL",
    "prices": [{"kind": "active_listing", "amount": 42.5, "currency": "GBP"}],
    "url": "https://www.vinted.co.uk/items/4210998877",
    "conditionText": "Very good",
}


@pytest.fixture()
def serve():
    """Run one handler on a loopback port for the duration of a test."""
    servers = []

    def start(search):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(SETTINGS, search))
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers.get("content-type"), json.loads(response.read())


def refused(url):
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(url)
    return caught.value


def no_search(base_url, query, platform):  # pragma: no cover - must never be called
    raise AssertionError("the search path must not run for this request")


def test_health_reports_the_protocol_version_and_the_source_it_serves(serve):
    """The version is the compatibility handshake, so it is a number, not prose.

    A sidecar reporting a version the app does not speak is not compatible
    with it, and the honest answer to that is a new sidecar release rather
    than a shim on either side.
    """
    base = serve(no_search)

    status, content_type, body = get(f"{base}/health")

    assert status == 200
    assert content_type == "application/json"
    assert body["status"] == "ok"
    assert body["protocol"] == PROTOCOL_VERSION
    assert body["sources"] == ["vinted_uk", "vinted_fr"]
    # This sidecar reads a public site and needs no credential, so it can
    # always answer. The app refuses to switch on a plugin that says otherwise.
    assert body["configured"] is True


def test_the_manifest_is_served_over_http(serve):
    """The declaring half of protocol 3, and the thing the app approves.

    Served from the same process as /search on purpose: a manifest fetched from
    somewhere else would describe a plugin nobody is talking to.
    """
    base = serve(no_search)

    status, content_type, body = get(f"{base}/manifest")

    assert status == 200
    assert content_type == "application/json"
    assert body["protocol"] == PROTOCOL_VERSION
    assert [source["id"] for source in body["sources"]] == ["vinted_uk", "vinted_fr"]


def test_the_manifest_never_calls_the_source(serve):
    # The app polls /manifest on every health tick, forever, exactly as it
    # polls /health. If declaring cost a scrape, an idle stack would be
    # hammering Vinted on a timer with nobody asking it to.
    base = serve(no_search)
    get(f"{base}/manifest")


def test_a_misconfigured_site_makes_the_manifest_a_500_naming_the_variable(serve):
    """A deployment pointed at a site this sidecar cannot describe.

    500 and not 404: the endpoint exists and the request was right. The app
    stores the body as the plugin's last error, which is where the operator
    reads it — so it has to name the variable to change.
    """
    elsewhere = Settings(
        sites=("xx",),
        port=0,
        catalog_ids=(),
        per_page=None,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(elsewhere, no_search))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        error = refused(f"http://127.0.0.1:{server.server_address[1]}/manifest")
        assert error.code == 500
        assert "VINTED_SITES" in json.loads(error.read())["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_health_never_calls_the_source(serve):
    """The deployment healthcheck runs every few seconds, forever.

    If it scraped, an idle stack would be hammering Vinted on a timer with
    nobody asking it to — and the pacing that would have to stop it lives in
    the app, which is not in this path.
    """
    base = serve(no_search)
    get(f"{base}/health")


def test_search_answers_a_json_array_of_raw_listings(serve):
    calls = []

    def search(base_url, query, platform):
        calls.append((base_url, query, platform))
        return [A_LISTING]

    base = serve(search)

    status, content_type, body = get(
        f"{base}/search?source=vinted_uk&q=ocarina%20of%20time&platform=n64"
    )

    assert status == 200
    assert content_type == "application/json"
    assert body == [A_LISTING]
    assert calls == [("https://www.vinted.co.uk", "ocarina of time", "n64")]


def test_each_source_searches_its_own_site(serve):
    calls = []
    base = serve(lambda base_url, query, platform: calls.append(base_url) or [])
    get(f"{base}/search?source=vinted_fr&q=zelda")
    assert calls == ["https://www.vinted.fr"]


def test_search_finding_nothing_is_an_empty_array_not_an_error(serve):
    base = serve(lambda base_url, query, platform: [])
    status, _, body = get(f"{base}/search?source=vinted_uk&q=a%20game%20nobody%20lists")
    assert (status, body) == (200, [])


def test_an_unknown_query_parameter_is_ignored_rather_than_refused(serve):
    """Later protocol versions add parameters; an old sidecar stays correct.

    `alt` is the live example rather than a hypothetical: the app sends a
    game's alternative names to every source, and this scraper has no use for
    them.
    """
    base = serve(lambda base_url, query, platform: [])
    status, _, _ = get(f"{base}/search?source=vinted_uk&q=zelda&alt=Zeruda&region=PAL&limit=5")
    assert status == 200


def test_a_search_without_a_query_is_a_client_error(serve):
    # `source` is supplied so this case fails on the missing `q` and not one
    # line earlier on the missing source: two guards return the same 400, and a
    # test named for one of them has to be the one that reaches it.
    base = serve(no_search)
    assert refused(f"{base}/search?source=vinted_uk").code == 400


def test_a_search_without_a_source_is_a_client_error(serve):
    """v2: one plugin may serve several sources, so every request says which.

    Refused rather than defaulted to the one this process serves. A caller that
    forgot the parameter is a caller with a bug, and answering it would file
    listings under whichever source this deployment happens to be.
    """
    base = serve(no_search)
    assert refused(f"{base}/search?q=zelda").code == 400


def test_a_search_for_another_source_is_a_404(serve):
    # This process cannot answer for a source
    # it does not serve, and saying so is not the same as saying the request
    # was malformed.
    base = serve(no_search)
    assert refused(f"{base}/search?source=vinted_de&q=zelda").code == 404


def test_a_failing_scrape_is_a_server_error_the_app_can_count(serve):
    """The app's circuit breaker counts non-2xx answers.

    So a scrape that blew up must reach it as a status, not as a 200 with an
    empty array — an empty array means "this source has nothing", which is a
    fact about Vinted rather than about the sidecar being broken.
    """

    def search(base_url, query, platform):
        raise RuntimeError("403 from the item endpoint")

    base = serve(search)
    assert refused(f"{base}/search?source=vinted_uk&q=zelda").code == 502


def test_an_unknown_path_is_a_404(serve):
    base = serve(no_search)
    assert refused(f"{serve(no_search)}/items/1").code == 404
    assert refused(f"{base}/").code == 404
