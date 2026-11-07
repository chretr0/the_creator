# New Worlds

Interactive Earth exploration and scenario sandbox (hackathon build). See [CLAUDE.md](./CLAUDE.md)
for product intent and [CLAUDE.mapping.md](./CLAUDE.mapping.md) for the map/H3 contract.

## What works now

- World map (MapLibre GL JS + OpenFreeMap basemap, attribution visible) with an H3 hex grid
  drawn by deck.gl's `H3HexagonLayer`.
- Display resolution is picked from an estimated on-screen cell budget (~5,000): a cached global
  overview at res 0–2, then viewport-bounded cells up to res 6. The full world is never enumerated
  at fine resolution, and views that cross the date line are split at ±180°.
- Click anywhere to inspect its **resolution-6 simulation cell** (ID, centre, area, pentagon/neighbours).
  The backend independently computes the cell and the inspector confirms both sides agree.
- Scenarios: create, rename, delete, and **branch** (copies projects onto the same baseline revision).
- Projects (data centre, solar, greenhouse): place at the exact clicked coordinate, edit
  name, type, coordinates and assumption parameters, move by clicking the map, and delete.
  Everything persists in Postgres and reloads exactly.
- Parameter fields list names and units only. No "typical" coefficients are filled in; blank means unknown.

- **Infrastructure layer** (ported from the bundled data in
  [gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)): 4,351 OSM datacenters and 703
  dams. They are drawn as footprints and dots, with stems in the 3D view and screen-grid labels.
  Datacenters are coloured by operator and can be filtered by company. Clicking one shows its
  operator and owner (separate OSM tags, Wikidata IDs), any tagged power-capacity rating, and
  provenance. Consumption is shown as *not reported*, because the source has none. "Model as
  data-centre project" places it in the scenario with blank assumptions. The 3D toggle tilts
  the map so OpenFreeMap's building extrusions show (zoom ≥ 14).

- **Context layers** (also adapted from gods-eye-view), in the sidebar's Layers / Search & rank /
  Data sources tabs:
  - *Boundaries:* Natural Earth countries and states/provinces, and US Census counties. All are
    public domain and simplified. The cell inspector shows each cell's region and counts of mapped
    datacenters and dams there.
  - *Submarine cables and landing points:* TeleGeography, **CC BY-NC-SA 3.0, non-commercial**.
    Delete `data/prepared/cables/` before any commercial use.
  - *Earthquakes:* USGS, M2.5+ over the last 7 days. *Active fires:* NASA FIRMS VIIRS, loaded
    for the current view. Fires need `NEWWORLDS_FIRMS_MAP_KEY`, a free key from
    https://firms.modaps.eosdis.nasa.gov/api/map_key/.
  - *Satellite imagery:* NASA GIBS tiles (VIIRS daily, HLS Sentinel-2/Landsat 30 m). A NASA CMR
    search lists recent dates over the view, with cloud cover.
  - *Electricity infrastructure:* OSM plants, substations and lines within 10 km of a cell, via
    Overpass. The disk cache keeps the demo working offline.
  - *Point weather:* Open-Meteo forecast from the GFS or ECMWF IFS model. This is forecast context
    only, not a resource assessment.
  - *Place search:* coordinates and bundled region names resolve without a network call. Other
    names fall back to Photon only when you ask for more results.
  - *Search & rank:* filters and ranks loaded records by dataset, region, operator, name and
    value. Unknown values sort last.
  - *Data sources:* licence, attribution, evidence type and limitations for every source.
    Attribution for active layers stays visible on the map.

Not built yet: measured baseline layers, the resource model, connections, and the comparison view.

### Refreshing infrastructure data

```bash
cd backend && uv run python ../scripts/prepare_infrastructure.py ../../gods-eye-view
```

This writes `data/prepared/infrastructure/` (ODbL 1.0, © OpenStreetMap contributors), served by
`GET /api/infrastructure` (provenance) and `GET /api/infrastructure/{datacenters|dams}`.

```bash
cd backend && uv run python ../scripts/prepare_reference.py ../../gods-eye-view
```

This writes `data/prepared/boundaries/` (public domain) and `data/prepared/cables/` (CC BY-NC-SA 3.0).
Live-source responses (USGS, FIRMS, Overpass) are cached under `data/cache/` (gitignored), and a stale
copy is served, marked as stale, when the upstream source is down.

## Layout

```
docker-compose.yml        Postgres 17 + Flyway
db/migrations/            Flyway SQL migrations (V<n>__description.sql)
backend/                  FastAPI + h3-py + psycopg (managed with uv)
frontend/                 React + TypeScript + Vite, MapLibre, deck.gl, h3-js
```

## Running locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
docker compose up -d db && docker compose run --rm flyway
```

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend on port 8000.

Postgres listens on host port **5433** (user/password/db: `newworlds`). Override the backend
connection with `NEWWORLDS_DATABASE_URL`.

### Migrations

Add a new file such as `db/migrations/V2__connections.sql`, then run
`docker compose run --rm flyway`. Never edit an applied migration. Add a new one instead.
To wipe the database: `docker compose down -v`.

### Tests

```bash
cd backend && uv run pytest
```

```bash
cd frontend && npm test
```

The backend API tests need the Docker database running.

## API

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Liveness + DB check |
| `GET /api/cells/locate?latitude=&longitude=&resolution=6` | Cell containing a coordinate |
| `GET /api/cells/{h3Id}` | Cell geometry, area, neighbours, parent |
| `GET/POST /api/scenarios` | List / create scenarios |
| `GET/PATCH/DELETE /api/scenarios/{id}` | Load (with projects) / rename / delete |
| `POST /api/scenarios/{id}/branch` | Branch a scenario |
| `GET /api/infrastructure[/{layer}]` | Datacenters / dams (region-tagged) + provenance |
| `GET /api/boundaries[/{layer}]`, `GET /api/cables[/{layer}]` | Boundary and cable packs + provenance |
| `GET /api/regions/locate`, `GET /api/regions/search-index` | Point → country/admin-1/county; local place index |
| `GET /api/hazards/earthquakes`, `GET /api/hazards/fires?west&south&east&north` | USGS / FIRMS (cached) |
| `GET /api/osm/power?latitude&longitude&radiusKm` | OSM plants, substations, lines (Overpass, cached) |
| `GET /api/sources` | Data credits registry |
| `POST /api/scenarios/{id}/projects` | Place a project (server computes the res-6 `h3Id`) |
| `PATCH/DELETE /api/projects/{id}` | Edit / move / remove a project |

Interactive docs: http://localhost:8000/docs

## Coordinate contract

- Stored locations: `latitude`, `longitude` (WGS84 degrees, `double precision`), longitude normalised to [-180, 180).
- H3 IDs are lowercase hex **strings** everywhere (JS, JSON, DB). They are never converted to numbers.
- Simulation resolution is fixed at 6. Changing the display resolution never changes a project's cell.

## Known limitations

- Web Mercator projection: latitudes beyond about ±85° are not displayed (cells exist, the map can't show them).
  A globe projection is a later option once tested with the H3 overlay.
- `highPrecision` hexagon rendering is on. The ~5,000 cell budget has not been benchmarked on the demo laptop yet.
