"""The HTTP surface: GET /health, GET /manifest and GET /search, and nothing else.

Standard library, not a framework, so the image's only pin is the scraper.
ThreadingHTTPServer so a slow scrape cannot block the healthcheck. No pacing,
retry, cache or timeout here: those belong to the app.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .config import Settings, load_settings
from .manifest import PROTOCOL_VERSION, SITES, UnknownSite, manifest_payload, source_id
from .search import search_listings

log = logging.getLogger(__name__)

#: (site base URL, query, platform hint) -> raw listings. Injected so the
#: surface can be exercised without a scraper, and so this module never imports
#: the package.
SearchFn = Callable[[str, str, Optional[str]], List[Dict[str, Any]]]


def health_payload(settings: Settings) -> Dict[str, Any]:
    """What /health says.

    `status` is about this process, not Vinted; the app's circuit breaker
    reacts to real search failures. `configured` is always True: a public site
    needs no credential. `package` is for humans diagnosing a stack.
    """
    return {
        "status": "ok",
        "protocol": PROTOCOL_VERSION,
        "configured": True,
        "sources": [source_id(key) for key in settings.sites],
        "package": {"name": "vinted_scraper", "version": _package_version()},
    }


def _package_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("vinted_scraper")
    except Exception:  # noqa: BLE001 - a missing package is a diagnostic, not a failure
        return None


def make_handler(settings: Settings, search: SearchFn):
    # source id -> base URL; an unknown key serves nothing and fails /manifest
    served = {source_id(key): SITES[key].base_url for key in settings.sites if key in SITES}

    class SidecarHandler(BaseHTTPRequestHandler):
        server_version = f"retrowatchdog-sidecar/{PROTOCOL_VERSION}"
        # a connection that never sends its request line releases its thread
        timeout = 30

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            route = urlparse(self.path)
            if route.path == "/health":
                self._json(200, health_payload(settings))
            elif route.path == "/manifest":
                self._manifest()
            elif route.path == "/search":
                self._search(parse_qs(route.query))
            else:
                self._json(404, {"error": f"no such endpoint: {route.path}"})

        def _manifest(self) -> None:
            try:
                self._json(200, manifest_payload(settings))
            except UnknownSite as error:
                # 500: the deployment is misconfigured; the app shows this as the plugin's last error
                log.error("cannot build a manifest: %s", error)
                self._json(500, {"error": str(error)})

        def _search(self, params: Dict[str, List[str]]) -> None:
            # Unknown parameters (e.g. `alt`) are ignored so the app can grow.
            # `source` is required: without it listings could be misattributed.
            source = _first(params.get("source"))
            if source is None:
                self._json(400, {"error": "source is required"})
                return
            base_url = served.get(source)
            if base_url is None:
                # 404: well formed, but not a site this process serves
                self._json(404, {"error": f"this sidecar does not serve {source!r}"})
                return
            query = _first(params.get("q"))
            if query is None:
                self._json(400, {"error": "q is required"})
                return
            try:
                listings = search(base_url, query, _first(params.get("platform")))
            except Exception as error:  # noqa: BLE001 - every failure is the app's to count
                log.exception("search failed")
                # a failure must be a status, never an empty 200: the app's breaker counts statuses
                self._json(502, {"error": f"{type(error).__name__}: {error}"})
                return
            self._json(200, listings)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            # one log stream, one format
            log.info("%s %s", self.address_string(), fmt % args)

    return SidecarHandler


def _first(values: Optional[List[str]]) -> Optional[str]:
    if not values:
        return None
    value = values[0].strip()
    return value or None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    handler = make_handler(
        settings, lambda base_url, query, platform: search_listings(settings, base_url, query, platform)
    )
    # every interface inside the container; compose publishes no host port for it
    server = ThreadingHTTPServer(("", settings.port), handler)
    log.info(
        "vinted sidecar serving %s on port %s (protocol %s)",
        ", ".join(source_id(key) for key in settings.sites),
        settings.port,
        PROTOCOL_VERSION,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
