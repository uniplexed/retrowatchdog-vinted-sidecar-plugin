# Vinted sidecar

A source plugin for [RetroWatchdog](https://github.com/uniplexed/retrowatchdog),
the manager of your retro game collection and your price hunts. It fetches
Vinted listings so the app can show private sellers' prices for the games you
hunt, speaking protocol version 3 as set out in the protocol document,
`docs/sidecar-protocol.md` in the `retrowatchdog` repository. It is a small
Python service wrapping the community package
[`vinted_scraper`](https://github.com/Giglium/vinted_scraper) (MIT), so the
part that breaks (cookie bootstrap, endpoint changes, Vinted's defences)
stays upstream where people maintain it. One process serves five `live`
sources, one per Vinted site: `vinted_uk`, `vinted_fr`, `vinted_de`,
`vinted_es` and `vinted_ie`. In a RetroWatchdog deployment it runs as the
compose service `vinted-sidecar-plugin` behind the `vinted` profile, from the
image `VINTED_SIDECAR_PLUGIN_IMAGE` names
(`retrowatchdog-vinted-sidecar-plugin:latest` by default), and the app offers
it as a pending plugin row on first boot from `VINTED_SIDECAR_PLUGIN_URL`
(`http://vinted-sidecar-plugin:8000`); you approve its role in Settings →
Plugins and switch on the countries you want in Settings → Markets. Nothing about it is
compiled into the app.

The general rules (what a plugin is, the fetch/interpret split, the manifest
and its approval, the isolation, the pacing) are in the protocol document;
this file covers only what this sidecar does within them.

## Terms of use: you need Vinted's authorization

Vinted's [terms and conditions](https://www.vinted.co.uk/terms_and_conditions) (checked
2026-10-18) forbid using "bots, scraping programs, crawling programs,
spiders" on the site "unless such a use is authorised, offered or in any
other way allowed by us", and forbid to "data mine, screen scrape, crawl" any
part of the site without Vinted's prior written consent. This plugin does
exactly that. Get Vinted's authorization before you run it; running it without
one is your decision and your responsibility. The plugin's manifest repeats
this under every Vinted price in the app. Each country site has its own
terms; read the one you use.

Vinted is also a scraping-hostile source: this is a best-effort integration
that may stop working without warning. Do not build a business on it.

## What it serves

| endpoint | answer |
|---|---|
| `GET /health` | `{status, protocol, configured, sources, package}`. `configured` is always `true`: a public site needs no credential. `sources` and `package` (the installed `vinted_scraper` version) are for humans; the app ignores them. |
| `GET /manifest` | one source per served site, each with its label, country, currency, reach, role, label and caveat; `requiredSecrets` is empty |
| `GET /search?source=<id>&q=<text>[&platform=<id>]` | a JSON array of raw listings |

Checking `/health` never calls Vinted: the deployment healthcheck runs every
30 seconds for the life of the container.

Status codes: `400` for a missing `source` or `q`; `404` for a source this
process does not serve or an unknown path; `502` when the scrape raises, so
the app's breaker counts it; `500` from `/manifest` when `VINTED_SITES`
names a site the sidecar cannot describe, with the variable in the body.
Unknown query parameters (`alt`, `spelling`, `budgetMs`) are ignored.
`platform` is accepted and not used, see "What is not verified". An empty
array is a fact about Vinted, not a failure.

## What it leaves to the app

The protocol's general rules apply unchanged: the sidecar fetches and never
classifies (no platform, region, completeness tier or grade leaves this
process), the app paces, retries, breaks and times out (its defaults are
`SIDECAR_RATE_LIMIT_MS` 3000, `SIDECAR_BREAKER_THRESHOLD` 5 failures held for
`SIDECAR_BREAKER_HOLD_MS` 30 minutes, and `ADAPTER_TIMEOUT_MS` 8000), and the
container holds no credential, database, volume or published host port and
sits on the `sidecars` network only. Two things are specific to this sidecar:

- It sends no `available`. The package's `is_visible` is not known to mean
  "buyable at that moment", and absent reads as unknown.
- It sends no `observedAt`. Absent means the moment of the search, which is
  what a live search is.

## What it declares

`kind: live`, `family: vinted`, `reach: global`, `defaultRegion: null`
(Vinted listings rarely declare a region and the app must not invent one from
the site's country), one expected currency per source, `kindRoles`
`active_listing → buy_listing` and nothing else, `kindLabels` "<site> asking
price", and a caveat saying the source is read by an unofficial community
scraper. Every Vinted number is an asking price from a private seller, never a
reference and never a shop's quote. No `sellFeeRate`: it is read only for a
`reference` reading.

The site decides country, currency and label. `app/manifest.py` holds the
sites the sidecar can describe, keyed as `VINTED_SITES` names them:

| key | source | site | country | currency | label |
|---|---|---|---|---|---|
| `uk` | `vinted_uk` | `https://www.vinted.co.uk` | GB | GBP | Vinted UK |
| `fr` | `vinted_fr` | `https://www.vinted.fr` | FR | EUR | Vinted France |
| `de` | `vinted_de` | `https://www.vinted.de` | DE | EUR | Vinted Deutschland |
| `es` | `vinted_es` | `https://www.vinted.es` | ES | EUR | Vinted España |
| `ie` | `vinted_ie` | `https://www.vinted.ie` | IE | EUR | Vinted Ireland |

Each site is its own source with its own catalogue, currency and stock, and
its own scraper session, so one site's cookie trouble fails only that source.
Adding a site is an edit by somebody who has looked at that site.

Vinted's condition field is a cosmetic grade ("Very good"), not a
completeness tier, so the app usually reads the tier as `unknown` and most
signals built on a Vinted listing are `potential` rather than `high`. That is
the correct outcome.

## How a listing is built

`app/mapping.py` reads one `vinted_scraper.models.VintedItem`. The fields
come from the package's own model source and README, not from an observed
Vinted response.

| package field | listing field | rule |
|---|---|---|
| `id` | `sourceProductId` | stringified; the protocol needs a non-empty string |
| `title` | `title` | verbatim; the app's cleaner and matcher are tuned on real seller text |
| `price` | `prices[0].amount` | as quoted, never converted; must be a finite non-negative number |
| `currency` | `prices[0].currency` | trimmed and upper-cased, then shape-checked as ISO 4217 |
| `url`, else `path` | `url` | kept when absolute `http(s)`, joined onto the site when site-relative, otherwise `null` |
| `status` | `conditionText` | the source's own words, unread |

One price of kind `active_listing`, always exactly one. An item that cannot
be mapped (no id, no title, a non-numeric price, a currency that fails the
shape check) is dropped with a warning and costs only itself; the rest of the
answer stands.

Not mapped: `service_fee` and `total_item_price` (a fee-inclusive asking
price has no kind in the protocol and would compare Vinted-plus-fees against
an eBay price without them); `brand_title`, `size_title` and `description`
(reading a platform or condition out of them is classification); `photos`,
`image`, `user`, `favourite_count`, `view_count`, `promoted`, `conversion`,
`item_box` and `search_tracking_params` (no fact the protocol asks for). No
`categoryText`: the model exposes no category field this mapping could trust.

`app/scrapers.py` builds one package scraper per site on first use and keeps
it, under a lock, since constructing one bootstraps a session cookie. The
package is imported inside that factory only, so every other module and the
whole test suite load without it. `reset_scrapers()` forgets the cache.

## Configuration

`app/config.py` reads four variables, all with defaults, so there is no
`.env.example`. In a RetroWatchdog deployment the plugin's own env file is
`.env.vinted` beside the app's `.env`, read with `required: false`.

| variable | default | meaning |
|---|---|---|
| `VINTED_SITES` | `uk,fr,de,es,ie` | comma-separated site keys to serve, from the table above |
| `PORT` | `8000` | the port inside the container; blank counts as unset |
| `VINTED_CATALOG_IDS` | `3002` | comma-separated Vinted catalogue ids to narrow every search to (`3002` is video games & consoles on every site) |
| `VINTED_PER_PAGE` | unset | page size to request |

## What is not verified

No test, script or build step in this repository calls Vinted. Each item
below could be wrong in a way the tests cannot catch.

1. Whether `search()` populates `url` on a search row: the package documents
   `item()` as populating only OpenGraph fields. Hence the `path` fallback,
   and the rule that a candidate which is neither absolute nor site-relative
   is left out. The app refuses the whole row over a link it cannot render,
   and a listing is worth more than a link.
2. Whether Vinted quotes `currency` as an uppercase ISO 4217 code in every
   locale. Hence the upper-casing and the shape check; a failing row is
   dropped, because the app converts by looking the code up, and a code its
   rate table cannot serve costs the source its whole block. The app also
   refuses, per source, any currency the site is not expected to quote.
3. What `status` reads in a non-English locale, and whether it is always
   populated. It travels verbatim either way.
4. The catalogue ids per country. The plugin sends them as the scraper's
   `attribute_ids[catalog]` (comma-separated); the web URL's `catalog[]` is
   ignored by the API, which then searches every category and returns books,
   films and clothes that share a game's name. Verified: "Video games & consoles"
   is `3002` on all five known sites (2026-10-18). A wrong id returns an empty result rather
   than an error, indistinguishable from "Vinted has none of these", so no id is
   guessed: `3002` is the default because it was checked on every site, and `platform`
   stays unused.
5. The `per_page` parameter name; unset by default for the same reason.
6. Whether the package's cookie bootstrap succeeds from a given network. The
   package's README documents frequent 403s and banned VPN ranges.

## How to build and run it

Goal: have the sidecar answering on the app's compose network and approved in
the app.

Prerequisites: Docker with the compose plugin, this repository checked out,
and a RetroWatchdog deployment to attach it to.

1. From this repository's root, run
   `docker build -t retrowatchdog-vinted-sidecar-plugin:latest .`. To use
   another tag, set `VINTED_SIDECAR_PLUGIN_IMAGE` in the app's `.env` to it.
2. From the app's directory, run
   `docker compose --profile vinted up -d vinted-sidecar-plugin`.
3. Run `docker compose logs vinted-sidecar-plugin`. The boot line reads
   `vinted sidecar serving vinted_uk, vinted_fr, vinted_de, vinted_es, vinted_ie on port 8000 (protocol 3)`.
4. In the app, open Settings → Plugins. The Vinted row is offered pending on
   first boot from `VINTED_SIDECAR_PLUGIN_URL`; press "Check now" and it reports a
   reply. Approve its role, then switch the market on in Settings → Markets.
5. Check: open a game; the Vinted block shows asking prices. A block reporting
   `error` after a search means the scrape raised, most often the package's
   cookie bootstrap; see "How to bump vinted_scraper".

The build context is this repository. The image is `python:3.12-slim`, the
server is the standard library's `ThreadingHTTPServer` (a slow scrape cannot
block the healthcheck), and the process runs as an unprivileged user and
publishes no host port.

## How to serve fewer countries

Goal: read only some Vinted sites.

1. In `.env.vinted`, set `VINTED_SITES` to the keys you want, for example
   `VINTED_SITES=uk,ie`.
2. Run `docker compose up -d vinted-sidecar-plugin`.
3. Check: Settings → Plugins shows the plugin's manifest changed; review and
   approve it. An unknown key shows as the row's last error, naming
   `VINTED_SITES` and the known keys.

A source left out stays declared nowhere, so its market disappears from
Settings → Markets. To keep a country declared but unread, leave it in and
switch its market off instead.

## How to bump `vinted_scraper`

Goal: adopt a new release of the community package. When the sidecar stops
returning listings, the fix is almost never in this repository.

1. Change the pinned version in `requirements.txt`. It is the only pin;
   `httpx`, which the package pulls in, is left unpinned so a security fix
   there needs no release here.
2. Read the release's changelog for a constructor or `search()` change;
   `app/scrapers.py` calls `VintedScraper(base_url)` and `search(params)`
   with `search_text`, and optionally `catalog[]` and `per_page`.
3. Run the tests below, then rebuild the image and recreate the container as
   in "How to build and run it".
4. Check: `/health` reports the new version under `package`, and a game shows
   Vinted asking prices again.

## How to run the tests

Goal: run this service's suite.

Prerequisites: Python 3.12 (the image's version) and `pytest`; nothing else.
`pytest` is not installed in the image, so the suite runs outside the
container. `vinted_scraper` need not be installed: every module loads
without it.

1. From this repository's root, run `python -m pytest`.
2. Check: pytest reports every test passed.

Every test is offline. There is no `fixtures/` folder: every item is a
hand-written stand-in built from the package's model fields, so the suite
pins this mapping, not Vinted's payload. If the package renames a field the
suite stays green and the sidecar returns nothing.

- `tests/test_config.py`: the five variables above.
- `tests/test_manifest.py`: what the sidecar declares per site, and the
  refusal of an unknown site.
- `tests/test_mapping.py`: what one item may become on the wire, and each
  refusal.
- `tests/test_search.py`: a stub scraper through `get_scraper`'s `factory`
  seam; one unmappable item costs that item and nothing else.
- `tests/test_server.py`: the three routes over a loopback socket with a stub
  search.

## How to regenerate the manifest fixture

Goal: keep `manifest.fixture.json` equal to what `app/manifest.py` produces
after a change to it, and record the change in the app.

The app keeps a recorded copy of this plugin's manifest and rows, as
`apps/api/src/adapters/sidecar/fixtures/vinted-manifest.json` and
`apps/api/src/adapters/sidecar/fixtures/vinted-search-2026-09-19.json` in the
`retrowatchdog` repository; its
`apps/api/test/adapters/sidecar/vintedManifest.test.ts` runs
`validateManifest` over the first, and its `vintedPluginContract.test.ts`
runs the app's parser over the second. A change to the manifest must be
recorded there.

Prerequisites: the test prerequisites above.

1. From this repository's root, run:

   ```bash
   python -c "import json; \
     from app.config import load_settings; from app.manifest import manifest_payload; \
     print(json.dumps(manifest_payload(load_settings({})), indent=2))" \
     > manifest.fixture.json
   ```

2. Copy `manifest.fixture.json` into the app repository as
   `apps/api/src/adapters/sidecar/fixtures/vinted-manifest.json`.
3. Check: the app's `vintedManifest` test passes.

The rows fixture is not regenerated: it holds the first six rows a running
sidecar answered for `q=pilotwings 64` on 2026-09-19, recorded verbatim. Its
first row is a magazine poster, and the fixture keeps it: the plugin fetches
it, and the app's non-game reading drops it.

## Legal

[LEGAL.md](LEGAL.md): the source's terms as last read, what they mean for
whoever runs this plugin, no warranty, not financial advice, no affiliation.
The names of the shops and marketplaces are their owners' trademarks, used
only to say where a price came from.

## License

Free software under the [GNU Affero General Public License v3.0](LICENSE),
and only that. Contributions are accepted under the terms in
[CONTRIBUTING.md](CONTRIBUTING.md).
