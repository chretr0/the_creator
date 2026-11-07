# New Worlds

Interactive Earth exploration and scenario sandbox (hackathon build). See [CLAUDE-Project-Overview.md](./CLAUDE-Project-Overview.md)
for product intent and [CLAUDE-World-Mapping.md](./CLAUDE-World-Mapping.md) for the map/H3 contract.

## What works now

- World map (MapLibre GL JS + OpenFreeMap basemap) with an H3 hex grid
  drawn by deck.gl's `H3HexagonLayer`.
- Display resolution is picked from an estimated on-screen cell budget (~5,000): a cached global
  overview at res 0–2, then viewport-bounded cells up to res 6. The full world is never enumerated
  at fine resolution, and views that cross the date line are split at ±180°.
- Click anywhere to inspect its **resolution-6 simulation cell**: place name, coordinates, area and baseline values.
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

- **Context layers** (also adapted from gods-eye-view), in the sidebar's Layers and Search tabs:
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
  - *Search:* filters and ranks loaded records by dataset, region, operator, name and
    value. Unknown values sort last.
  - *Data sources:* licence and attribution for every source are served by `GET /api/sources`
    (not shown in the UI).

- **Baseline data** (sidebar *Layers* tab, built from `data/prepared/`; see [data/STATUS.md](./data/STATUS.md)):
  - *Colour cells by* one H3 layer: NASA POWER solar (all-sky and clear-sky GHI), temperature, precipitation and
    wind (long-term monthly climatology and each month of 2024); GHSL and WorldPop population density; GHSL
    built-up share; VIIRS 2024 fire detections; SoilGrids pH, organic carbon, clay, sand, nitrogen and bulk
    density at two depths (global). Copernicus DEM elevation/slope and ESA WorldCover land cover are prepared
    for the Arizona and UK regions only. Zoomed-out hexagons show the mean (or density of the total, or most
    common class) of the resolution-6 cells inside them. Grey cells are unknown, never zero.
  - *Mapped records*: USGS MRDS mineral sites (global, filter by status and text such as a commodity), EPA TRI
    facilities and Water Quality Portal sites (Arizona), NSTA offshore wellbores (UK), Aqueduct 4.0 baseline and
    projected water stress, HydroRIVERS and HydroBASINS level 6 (both regions), and the NESO regional carbon
    intensity table (Great Britain).
  - *Prices* (global, every land cell): average **electricity** (USD/kWh) and **water + wastewater** (USD/m³)
    prices, household and business. One average per country, or per state/province for US, Canadian and Australian
    electricity. Day/night, seasonal and tiered tariffs are averaged into one rate. Sources: US EIA (by state),
    Eurostat, and a cited research table ([data/reference/utility_prices/](./data/reference/utility_prices/README.md)).
    The cell inspector shows each value's local price, exchange rate, year, source and method. Water is unknown
    (grey) for about a quarter of land, mainly North Africa and the Sahel, Iran/Iraq/Afghanistan, Central Asia,
    Mongolia and Myanmar. US water is a national 50-city average, except Arizona (Phoenix tariff).
    Rebuild with `scripts/prepare_utility_prices.py`.
  - Clicking a cell now lists every layer's value for that cell (with monthly charts), the water-risk basin
    it sits in, rivers crossing it, and the nearest records from each point layer.

- **Building system** ([CLAUDE.Building-System.md](./CLAUDE.Building-System.md)), in the sidebar's *Build* tab
  (or *+ Add building*):
  1. *Define*: pick Power station, Water plant, Data centre, Solar, Greenhouse or Custom, add a name and a
     description, and fill in whatever statistics you know: footprint, hours, power use/output, water use/output,
     raw materials, air emissions, light, workers and costs. Blank means unknown, never zero; no typical values are
     filled in. Definitions can be saved and reused.
  2. *Requirements*: map-layer limits (any registered H3 layer), site area, power/energy/water supply, budgets,
     staffing, light and emission limits. Each is optional or required.
  3. *Find locations*: screens resolution-6 cells in the current view or the Arizona/UK region and colours them
     *meets criteria* / *more information needed* / *fails*, with a candidate list.
  4. *Preview and place*: re-assesses the exact point (water stress uses the Aqueduct basin containing it) and
     shows every check with values, units and sources. *Build here* saves a snapshot of the definition, so later
     definition edits never change placed buildings.
  - *Real examples*: cards for real facilities (Palo Verde nuclear, Mesquite gas, Agua Caliente solar, Carlsbad
    desalination, Meta Prineville data centre, Thanet Earth glasshouse) with figures cited to public sources; drag a
    card onto the map to place a new building with those figures. Unknown figures stay blank.
  - *Scenario controls* (Projects tab): evaluation period, pooled resource budgets, and stress multipliers for water
    and power availability, operating demand and prices, with unstressed vs stressed totals and per-building
    shortfalls. Branching copies buildings, budgets and controls.

Not built yet: connections between buildings and the cross-scenario comparison view. Manual-download sources
([data/MANUAL-DOWNLOADS.md](./data/MANUAL-DOWNLOADS.md)) appear once they are prepared: add a `LayerDef` in
`backend/app/layers.py` for an H3 layer, or a manifest entry in `data/prepared/features/manifest.json` for records.

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

### Preparing the baseline data

Regional H3 layers (DEM, WorldCover, GHSL built-up), record layers and scene PNGs are built from `data/raw/`:

```bash
uv run --no-project --with rasterio --with duckdb --with pyarrow --with numpy python -I scripts/prepare_regional_h3.py
```

```bash
uv run --no-project --with geopandas --with pyogrio --with shapely --with pyarrow --with numpy python -I scripts/prepare_feature_layers.py
```

```bash
uv run --no-project --with rasterio --with numpy --with pillow python -I scripts/prepare_imagery.py
```

Satellite and reanalysis layers (ERA5-Land and CAMS 2024 monthly, GRACE, SMAP, SWOT, GEDI, MODIS NDVI, ECOSTRESS,
PACE, EMIT, Sentinel-5P) are aggregated to resolution-6 cells and appear in *Colour the grid* with month/date variants.
Grids coarser than a cell are sampled at each cell centre (like POWER); finer pixels are averaged per cell:

```bash
uv run --no-project --with xarray --with netcdf4 --with h5netcdf --with rasterio --with pyproj --with pyhdf --with duckdb --with pyarrow --with numpy --with h3 python -I scripts/prepare_observation_h3.py
```

Aqueduct 4.0 baseline water stress (Arizona and UK) comes from `scripts/build_layers.py`, which writes
`data/prepared/layers/water_stress_baseline/{arizona,uk}.parquet`. Each cell takes the basin containing its centre;
the index is never averaged, so zoomed-out hexagons show the most common class, and "No Data" basins stay blank.

Regional layers outside the Arizona and UK boxes are blank, and the data panel says *No baseline data for this
area*. Each value in the cell inspector has a *Source* block (units, period, native resolution, evidence type,
caveats, licence and attribution from `data/raw/<ID>/<region>/source.json`). The map always shows the basemap
credit and the active sources, linked to the *Data sources & licences* list in the Layers tab.

`GET /api/imagery` lists the prepared Globe–Miami scene clips (Sentinel-2, Landsat 8), drawn from the Data tab.

### Baseline layer cache

The first request for a layer slice reads its Parquet column once and writes memory-mapped arrays (resolution 6
plus aggregated levels 0–5) to `data/cache/h3/`. Later requests are lookups. The backend warms the default
solar layer at start-up. Delete `data/cache/h3/` to rebuild; it is regenerated from `data/prepared/`.

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
| `GET/PATCH/DELETE /api/scenarios/{id}` | Load (with projects) / rename / delete; PATCH `assumptions` merges top-level keys (`periodDays`, `budgets`, `stress` validated) |
| `POST /api/scenarios/{id}/branch` | Branch a scenario |
| `GET /api/infrastructure[/{layer}]` | Datacenters / dams (region-tagged) + provenance |
| `GET /api/boundaries[/{layer}]`, `GET /api/cables[/{layer}]` | Boundary and cable packs + provenance |
| `GET /api/regions/locate`, `GET /api/regions/search-index` | Point → country/admin-1/county; local place index |
| `GET /api/hazards/earthquakes`, `GET /api/hazards/fires?west&south&east&north` | USGS / FIRMS (cached) |
| `GET /api/osm/power?latitude&longitude&radiusKm` | OSM plants, substations, lines (Overpass, cached) |
| `GET /api/sources` | Data credits registry |
| `GET /api/layers` | H3 baseline layers: slices, units, colour hints, availability, provenance |
| `POST /api/layers/{id}/values` `{slice, cells}` | Values for display cells (res 0–6), aligned with the request; `null` = no data |
| `GET /api/cells/{h3Id}/profile` | Every H3 layer's values (all slices) for a cell of resolution 0–6, with source, licence and caveats per layer |
| `GET /api/features`, `GET /api/features/{id}?west&south&east&north&category&q&limit` | Record layers (points, lines, polygons, tables) |
| `GET /api/cells/{h3Id}/features` | Containing polygons, crossing rivers, and nearest records for one res-6 cell |
| `POST /api/scenarios/{id}/projects` | Place a project (server computes the res-6 `h3Id`); optional `definition` snapshot, `sourceDefinitionId`, `site` |
| `PATCH/DELETE /api/projects/{id}` | Edit / move / remove a project |
| `GET /api/building-templates` | Predefined building types (power station, water plant, data centre, solar, greenhouse, custom): fields, units, help; no numeric defaults |
| `GET /api/building-presets` | Real example buildings: stats and parameters with cited provenance, sources, notes and reference site (read-only) |
| `GET/POST /api/building-definitions`, `GET/PATCH/DELETE /api/building-definitions/{id}` | Saved building definitions; edits/deletes never change placed snapshots |
| `POST /api/building-assessments` | Read-only calculation + pass/fail/unknown checks for a draft at an exact `location`, or over `bounds`/`region` res-6 cells (limit 30,000, else 422) |
| `POST /api/scenarios/{id}/evaluate` `{stress?, periodDays?, budgets?}` | Unstressed vs stressed per-building results, pooled budgets and totals |

Interactive docs: http://localhost:8000/docs

## Coordinate contract

- Stored locations: `latitude`, `longitude` (WGS84 degrees, `double precision`), longitude normalised to [-180, 180).
- H3 IDs are lowercase hex **strings** everywhere (JS, JSON, DB). They are never converted to numbers.
- Simulation resolution is fixed at 6. Changing the display resolution never changes a project's cell.

## Known limitations

- Web Mercator projection: latitudes beyond about ±85° are not displayed (cells exist, the map can't show them).
  A globe projection is a later option once tested with the H3 overlay.
- `highPrecision` hexagon rendering is on. The ~5,000 cell budget has not been benchmarked on the demo laptop yet.
