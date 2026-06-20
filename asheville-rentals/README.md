# Asheville Rentals

A self-contained, single-page rental finder for a fixed list of Asheville-area
apartment complexes. It scrapes each complex's **first-party** availability feed,
saves the results to `data.json`, and shows them in a sortable, filterable table.

Everything lives in this one folder and has **zero npm dependencies** — it only
needs Node 18+ (uses the built-in `fetch` and `http`). Copy the folder anywhere
to run it.

## Run

```bash
node server.mjs          # -> http://localhost:5173
```

Open the page and click **Refresh all sources** to (re-)scrape every complex.
You can also scrape from the command line without the server:

```bash
node scrape.mjs          # writes data.json
```

`PORT=8080 node server.mjs` to change the port.

## How it works

```
asheville-rentals/
  server.mjs     zero-dep HTTP server: serves index.html, GET /api/data, POST /api/refresh
  scrape.mjs     loads every adapter in sources/, runs them in parallel, writes data.json
  index.html     the page: sortable table, filters, per-source status, Refresh button
  data.json      saved results (regenerated on every refresh)
  sources/
    _lib.mjs                    shared fetch + parsing helpers
    <complex>.mjs              one adapter per complex (meta + fetchListings())
```

Each `sources/<complex>.mjs` exports:
- `meta` — name, address, official URL, fees (pet/parking/W-D), outdoor space, W/D type
- `fetchListings()` — returns normalized rows `{ floorplan, unit, beds, baths, sqft, price, available, granularity }`

`scrape.mjs` merges `meta` onto every row and writes `{ generatedAt, sources[], listings[] }`.

To add a complex, drop another `sources/<name>.mjs` in (files starting with `_`
are ignored). To remove one, delete its file.

## Data sources & known limits

All feeds are first-party (the aggregators — apartments.com, zillow.com,
realtor.com — actively block automated requests, so they are not used).

**Direct fetch (live, per-unit):**
- Ascot Point Village — myleasestar API
- Hawthorne at Bear Creek — RentCafe API
- The District — Knock API
- Reserve at Biltmore Park — embedded JSON on floorplan pages
- Eastwood Village — official floorplan pages (per-unit apply links)

**Via render proxy (`r.jina.ai`) — needed because these sit behind Cloudflare /
RealPage bot-walls a plain fetch can't pass:**
- Retreat at Arden Farms — RentCafe (floorplan-level)
- Heritage at the Peak — RentCafe (floorplan-level)
- Vetra Asheville — RealPage leasing app (floorplan-level)

  > The proxy is a free public service with rate limits and occasional
  > challenge stubs, so the adapter retries. These three give **floorplan-level**
  > pricing (the per-unit list is loaded only after a click and isn't in the
  > rendered HTML). If the proxy is down, these sources report "no live data"
  > and the rest of the table still works.

**Not available:**
- Goldelm at the Views — its RealPage unit feed is behind DataDome + Akamai bot
  management that neither a plain fetch nor the proxy can pass; it requires a full
  headless browser doing the site's token handshake. It still appears in the table
  (with fees/amenities) marked "see site," linking to its official availability page.

Rows are labelled `floorplan` (floorplan-level) or `see site` so it's always clear
which granularity you're looking at. Fees, outdoor-space, and W/D-type columns come
from each complex's published amenity/fee info and change rarely.
