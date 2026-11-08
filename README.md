# New Worlds

Interactive Earth exploration and scenario sandbox (hackathon build), now with a first Moon module. See [CLAUDE-Project-Overview.md](./CLAUDE-Project-Overview.md)
for product intent, [CLAUDE-World-Mapping.md](./CLAUDE-World-Mapping.md) for the map/H3 contract and
[CLAUDE-Moon-Data-Sources.md](./CLAUDE-Moon-Data-Sources.md) for the Moon data catalogue.

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

- **Infrastructure section** (Explore → Infrastructure), grouped as Energy & grid, Digital, Transport
  and Resources & industry. Each layer loads the first time it is switched on or searched:
  - *Datacenters* (4,351) and *dams* (703): OSM, from the bundled data in
    [gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view). Drawn as footprints and dots,
    with stems in the 3D view and screen-grid labels. Datacenters are coloured by operator and can be
    filtered by company. "Model as data-centre project" places one in the scenario with blank assumptions.
  - *Power plants* (34,936): WRI Global Power Plant Database v1.3 (CC BY 4.0), coloured by fuel and
    sized by nameplate MW. Shows owner, commissioning year and the latest annual generation, flagged
    when it is WRI's model estimate. The database stopped updating in 2021.
  - *Substations* (3,186) and *high-voltage lines* (27,716 segments, ~59,000 km): OSM features at
    66 kV or more, for the prepared regions (Arizona, UK) only, coloured by voltage. Elsewhere use
    "Load OSM power here" on a location.
  - *Airports* (5,282 large and medium, OurAirports, public domain) and *seaports* (1,081, Natural
    Earth, public domain).
  - *Submarine cables and landing points*, and toggles for the mineral sites, UK offshore wellbores
    and TRI industrial facilities from Mapped records.

  Clicking a site shows operator and owner (kept separate, never back-filled), capacity or voltage,
  and links to the source record. Consumption is shown as *not reported*, because no source has it.
  The 3D toggle tilts the map so OpenFreeMap's building extrusions show (zoom ≥ 14).

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
  1. *Define*: pick one of 42 building types in ten categories (energy: power station, solar, wind, hydro,
     geothermal, battery storage, hydrogen; water and wastewater plants; mines, quarries, oil & gas fields;
     factories, steel, aluminium, cement, chemicals, refineries, semiconductor fabs; crop and livestock farms,
     greenhouses, vertical farms, aquaculture, food processing; data centres, offices, retail, hotels, labs;
     housing, hospitals, schools, universities, stadiums; airports, seaports, warehouses; landfill, recycling,
     waste-to-energy; or Custom), add a name and a description, and fill in whatever statistics you know: footprint, hours, power use/output, water use/output,
     raw materials, air emissions, light, workers and costs. Blank means unknown, never zero; no typical values are
     filled in. Definitions can be saved and reused.
  2. *Requirements*: map-layer limits (any registered H3 layer), site area, power/energy/water supply, budgets,
     staffing, light and emission limits. Each is optional or required.
  3. *Find locations*: screens resolution-6 cells in the current view or the Arizona/UK region and colours them
     *meets criteria* / *more information needed* / *fails*, with a candidate list. Building types with a site
     profile (farms, greenhouses, solar, wind, hydro, data centres, industry, housing and services, …) are also graded
     *ideal* / *good* / *marginal* / *unsuitable* from every relevant prepared layer (soil nitrogen, pH, organic
     carbon, texture, rainfall, growing season, slope, land cover, NDVI, water stress, prices, population …); the map
     legend can colour by the overall grade or any single factor, and the site panel lists each factor's value and band.
     Map layers about what the building needs (power grid for electricity, rivers and dams for water, mineral sites for
     materials …) switch on automatically while you build and off again when you leave.
  4. *Preview and place*: re-assesses the exact point (water stress uses the Aqueduct basin containing it) and
     shows every check with values, units and sources. *Build here* saves a snapshot of the definition, so later
     definition edits never change placed buildings.
  - *Real examples*: cards for real facilities (Palo Verde nuclear, Mesquite gas, Agua Caliente solar, Carlsbad
    desalination, Meta Prineville data centre, Thanet Earth glasshouse) with figures cited to public sources; drag a
    card onto the map to place a new building with those figures. Unknown figures stay blank.
  - *Capacity margins*: each comparable resource shows **Tile provides / Needs / Margin**. Margin is available
    supply minus this building's requirement, after nearby projects are accounted for. Negative means shortfall;
    unknown inputs stay unknown. Air/light indicators with incompatible units are not subtracted.

- **Timeline** replaces the Scenarios / stress-testing UI. Scrub or play from day 0 to five years,
  choose a receiving environment and pollutant, and view illustrative added impact. Where compatible measured
  backgrounds exist, historical Baseline and Combined views are also available.
  Placed buildings are listed (and opened for editing) at the top of **Build**. Worlds are switched, added, branched,
  renamed and deleted from the **Active world** menu in the header. Existing scenario records and APIs remain compatible.
  - The slider starts at **day 0**, when operation begins, then steps through round intervals that each go further
    than the last: 1, 2, 4 and 8 hours; 1, 2 and 4 days; 1 and 2 weeks; 1, 3 and 6 months; 1, 2 and 5 years.
    Months and years are whole days rounded from 365.25 days/year (30, 91, 183, 365, 731 and 1,826 days).
    Previous/next buttons use the same steps. Playback advances every 500 ms and stops at five years; Reset returns
    to day 0, where nothing has been released yet.
    **Colour scale** is either *Fixed five-year* (colours relative to the five-year peak, so steps are comparable) or
    *Fit this step* (colours relative to the frame shown; compare steps by the legend maximum). Accumulated air
    exposure defaults to *Fit this step*, because the first steps are a tiny fraction of the five-year peak and would otherwise be
    invisible; every other view defaults to *Fixed five-year*. A choice the viewer makes is kept. Opacity is linear
    in the value, so faint plume tails are not visually amplified. Colours are relative to the displayed estimate,
    not health/safety thresholds.
  - The Environment and Pollutant lists only offer what the world's buildings declare. Releases with an unknown rate
    are listed (and reported as missing inputs); releases declared at exactly zero are not. A world with no
    releases shows a prompt to add them in the building editor.
  - All projects start at day zero. Emission mass and resource use accumulate from declared operating hours and rates,
    using the existing calculator without legacy stress multipliers. Unknown project contributions are explicitly excluded
    from *known subtotals*, never treated as zero. The API is read-only and does not change source measurements.
  - **Air defaults to Accumulated exposure**, the integral of added concentration since operation began, in
    **µg·day/m³**. This continues increasing as releases continue, even when local air concentration has settled.
    **Concentration now** remains a separate view in **µg/m³**. Both use the same transport assumptions. The cumulative
    quantity is not the mass currently in the air or an inhaled dose. For continuous emissions it integrates each
    age-dependent transport kernel with weight `(elapsed days − puff age in days)`, accounting for arrival time,
    rather than multiplying the final concentration by elapsed time. Baseline/Combined exposure views integrate the
    fixed CAMS historical mean as a reference; the underlying measurements remain unchanged. Soil, water and CO₂e
    keep their existing measures and units. No API or database changes are required.
  - Air uses a **prototype Gaussian puff illustration**, not a forecast or regulatory dispersion model.
    Equation basis: [NOAA's Gaussian horizontal puff concentration](https://www.ready.noaa.gov/documents/AMS2018/html/conc_eqns.html).
    This implementation is not HYSPLIT. It assumes constant wind, uniform vertical mixing, an initial horizontal standard
    deviation of 750 m, and continuous emissions at each building's daily average.
  - **Wind is local by default.** Each building's releases drift with the long-term climate wind at its own location:
    the NASA POWER MERRA-2 annual-mean 10 m wind vector (`U10M`, `V10M`; ~0.5° × 0.625° grid, nearest grid cell).
    Averaging the components gives the **net drift**: winds that change direction cancel out, so it is slower than the
    average wind speed (also shown) and is not the most frequent direction. Day-to-day weather is not modelled, and the
    grid is too coarse for terrain or coastal effects. Buildings with different winds are superposed. *Custom wind*
    applies one assumed wind to every building instead (default 3 m/s from 270°); if a building has no local wind it
    uses that assumed wind, and the panel says so. Mixing height (500 m) and horizontal diffusion (200 m²/s) stay
    editable **illustrative assumptions** either way. The wind grid is a small committed file,
    `data/prepared/power_wind10m_annual_grid.npz` (~0.7 MB), rebuilt with `scripts/fetch_power_wind.py`.
    Concentration integrates a fixed 2,048-interval logarithmic puff-age grid spanning the supported ten-year calculation
    range (the UI ends at five years), with variance `750² + 2 × diffusion × age`. Each frame includes only ages up to
    its elapsed time; intervals do not shift during playback. Mass is conserved in the unbounded mathematical domain.
    Display is bounded to eight simulation-cell rings (roughly 50 km, varying with location)
    around projects, sampled at resolution-7 display-cell centres. The finer display repeats each parent's coarse
    background; it does not create finer atmospheric observations. Up to 25,000 display cells are supported per world.
    Each receptor only evaluates the puffs whose exp(−40) footprint can reach its distance from the source (a
    binary search for the first, an early stop after the last), giving identical results to a full scan. With 25,000
    cells and three sources a frame takes about 40 ms in the default wind and up to about 400 ms in calm air at five years.
  - PM2.5/PM10 can use the **CAMS 2024 annual mean** (~80 km native grid) as a fixed background. These are historical
    reference conditions, not current readings. CO₂ has no supplied background, so only its added mass concentration is
    shown; atmospheric-column products are never substituted for surface concentration. No chemistry, deposition,
    terrain, stack/plume rise, weather evolution or climate warming is modelled. Local concentrations can level off as
    pollution moves away while cumulative emitted mass keeps growing. At the default 3 m/s, air travels 10.8 km/hour
    (259.2 km/day), so the plume crosses the ~50 km local display within the first few hours.
    The panel explains this speed and distinguishes instantaneous concentration, accumulated exposure and cumulative
    released mass. The map legend, peak metric and tooltips use the units of the selected measure.
  - **Pollutants & releases** uses the shared `shared/pollutants.json` catalogue (39 identities): gases and particles,
    metals, nutrients, oils, solids, pesticides, PFAS and microplastics. Select a destination, pollutant and hourly rate.
    `Other / existing pollutant` preserves unlisted legacy names and distinct mass bases. Missing `medium` in old
    records defaults to air, except recognised CO₂e names (including annotated Scope 1+2 labels), which resolve to
    climate accounting. Values and original labels are preserved; no database migration is needed. The same chemical
    released into two environments is calculated and assessed separately. Only air releases trigger air site checks.
  - **Soil** adds `rate × days × 1e6 / (2πσ² × depth × density) × exp(-distance²/(2σ²))` in **mg/kg** on land cells.
    Editable prototype defaults: 1 km σ, 0.2 m mixing depth, 1,300 kg/m³ soil density. No leaching, runoff or decay.
  - **Rivers & freshwater** assumes the nearest HydroRIVERS reach within 10 km as the receiving river. Prepared
    NEXT_DOWN connections determine direction (including upstream links for terminal reaches), for up to 30 km.
    Arrival time uses an editable assumed speed (0.3 m/s); the increment is `kg/day / 86400 / flow(m³/s) × 1000`
    in **mg/L**, with complete mixing and long-term average discharge. Missing flow or routing leaves concentration
    unknown. No lake storage, tides, treatment, sedimentation or chemistry is simulated. Actual outfalls are unverified.
  - **Sea & coastal water** uses a separate Gaussian tracer with adjustable assumed current (0.1 m/s from 270°),
    mixing depth (10 m) and diffusion (20 m²/s), displaying **mg/L** only on sea cells. An illustrative outfall is
    snapped to the nearest sea cell within 20 km; otherwise its concentration stays unknown. Land/sea classification
    uses simplified country boundaries, not a hydrodynamic coastline or inland-water mask. Shoreline clipping does
    not redistribute mass. No tides, chemical reactions or shoreline reflection are simulated.
  - **Climate (CO₂e)** maps cumulative declared contributions at building source cells in **kgCO₂e**, including any
    indirect emissions already in the declared rate. It does not disperse accounting equivalents as a physical gas.
    Physical CO₂ remains separate, with no assumed GWP conversion or automatic addition to CO₂e. See the
    [EPA explanation of greenhouse gas accounting](https://www.epa.gov/ghgemissions/overview-greenhouse-gases).
  - Soil, river and sea baselines remain unknown; point samples and atmospheric column measurements are not repurposed
    as compatible backgrounds. The UI shows model assumptions, units, unavailable receiving environments and partial
    contributions. Building markers use independent MapLibre DOM markers above the pollution overlays, so every
    placed building remains selectable when pollutants, time, theme or map pitch change.

- **World totals** (the tab next to the **Active world** menu) adds up everything the active Earth world's buildings
  declare, per day, month or year (`POST /api/scenarios/{id}/evaluate` with `periodDays`; nothing is saved):
  construction and operating cost (one total per currency, never converted), electricity and water generated, used
  and net (generated − used), summed peak demand (an upper bound), land used, staff, worker capacity, upward light,
  emissions by pollutant and receiving environment, materials, and each building's share. A total that some buildings
  don't declare is marked *partial* or *unknown* (never 0); hover it for the buildings and inputs that are missing.

Not built yet: connections between buildings and the cross-scenario comparison view. Manual-download sources
([data/MANUAL-DOWNLOADS.md](./data/MANUAL-DOWNLOADS.md)) appear once they are prepared: add a `LayerDef` in
`backend/app/layers.py` for an H3 layer, or a manifest entry in `data/prepared/features/manifest.json` for records.

### Refreshing infrastructure data

```bash
uv run --no-project --with h3 --with pyshp python -I scripts/prepare_infrastructure.py --gev ../gods-eye-view
```

This writes `data/prepared/infrastructure/` with one provenance record per source in `source.json`,
served by `GET /api/infrastructure` and `GET /api/infrastructure/{layer}`. Leave out `--gev` to keep
the existing datacenter and dam files; add `--fetch` to re-download the power plant, airport and port
sources. The grid layers are read from the Overpass tiles in `data/raw/GRID-OSM/` (fetch them with
`scripts/prepare_power_grid.py --fetch`). `power_plants.geojson` and `transmission_lines.geojson`
are gitignored (18 MB and 14 MB); the app marks them "Not prepared" until this script has run.

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

## Bodies: Earth and the Moon

The app is body-modular. Earth and the Moon share the H3 grid, the map component, the cell model and the
evidence rules. H3 cell IDs are the same on both; only lengths (× R) and areas (× R²) change. Each body
plugs in through a small registry:

- **Backend:** `app/bodies.py` holds the registry (Earth R = 6371.0072 km, h3's authalic radius; Moon
  R = 1737.4 km, IAU_2015:30100). It provides body-aware cell area, edge length, great-circle distance and
  geodesic circles. `/api/cells/*?body=moon` returns Moon areas. Moon-only routes live under
  `/api/moon` (`routers/moon.py` for the reference layers, `routers/moon_layers.py` for the H3 data layers).
- **Frontend:** `src/bodies/` defines each body: basemap style, initial view, radius, whether day/night
  theming and 3D tilt apply, and credits. `src/App.tsx` is a shell that mounts either `src/earth/EarthApp.tsx`
  (the existing app, unchanged) or `src/moon/MoonApp.tsx`. Only one is mounted at a time, so no Earth data is
  ever fetched for Moon coordinates; Earth's regional boxes would otherwise also match Moon lat/lon. The
  header's Earth | Moon switch (also `?body=moon`) picks the body. `WorldMap` takes a `body` prop and draws a
  body-aware scale bar, because MapLibre's own scale and deck.gl metre units assume Earth's radius. Moon
  overlays are therefore drawn in pixel units or as lat/lon polygons computed on the Moon sphere.

**Explore on the Moon:**

- **Map:** LROC WAC basemap (Lunaserv WMS). Overlays: IAU feature names, hillshade, colour relief,
  permanently shadowed regions and mare outlines.
- **Place search:** 9,087 IAU features plus coordinates.
- **Landed objects (73, from LROC):** coloured by kind, with the six Apollo landings highlighted.
- **Planned missions and Artemis candidate regions:** marked as planned, dated "as of 2026-11-08".
- **Heritage keep-out rings:** NASA 2011 recommendations, 2 km around landings and 0.5 km around impacts.
- **Elevation:** a LOLA H3 layer at res 0–5 (16 ppd source).
- **Location inspector:** Moon area and edge length, elevation, mare, LAC quad, nearest named features,
  nearby landed objects and keep-out status.
- **Sources:** a sources & licences list.

**Build on the Moon (hypothetical base):** shows what the app can do once the right data exists. It reuses
the worlds and buildings tables: a world has a `body` (`earth` | `moon`, migration V4), the Earth app lists only
Earth worlds and the Moon's Build workspace only Moon worlds, and each kind of world accepts only its own
building types.

- **Building types** come from `shared/moon_buildings.json` (read by both sides, like `shared/pollutants.json`):
  crew habitat, vertical solar array, fission surface power, night power storage, ice mining plant, oxygen plant,
  greenhouse and landing pad. Defaults are taken from the Moon catalogue §10–11 and tagged by source: NASA
  requirement or contract value, company claim, estimate, derived, or illustrative assumption. Every value is editable;
  a blank value is unknown, never zero. The backend (`app/moon_buildings.py`) validates ranges.
- **Site check** (`frontend/src/moon/buildings.ts`), for the clicked point:
  - Heritage keep-out rings veto a site.
  - Landing pads keep other buildings outside their plume radius (default 2 km). Reactors keep habitats and
    greenhouses outside their radiation radius (default 1 km). Both rings are drawn on the map.
  - Buildings within 5 km are assumed to share one power and supply network.
  - Habitats need Earth in view: always on the near side, intermittent near the limb, never on the far side.
  - Solar arrays get 50% sunlight on flat ground away from the poles. Near the poles it depends on terrain, so the
    user enters a surveyed sunlit fraction there.
  - Ice mines need polar latitudes.
  - Oxygen plants and landing pads prefer mare ground (from the mare outlines).
  - LOLA elevation is shown. Slopes are not checked, because the prepared grid is too coarse.
- **World totals** (the tab next to the **Active world** menu, as on Earth) adds up the base:
  - Crew housed, and per-person oxygen, water and food (NASA BVAD), less what the habitat recycles, against what
    the oxygen plant, ice mine and greenhouse make.
  - Power by day, and through the night (~14.8 days away from the poles, 120 h for an all-polar ridge base, or a
    value set for the base): fission plus storage.
  - Landed mass and the cost to deliver it, and the yearly resupply from Earth, at four transport prices from
    $600/kg to $146,700/kg.
  - A headline that says whether the base keeps its crew alive, and whether it needs deliveries from Earth to do so.
  - Each building's share: daytime power it adds or draws, landed mass and delivery cost, with the base's totals.
- Not modelled: day-to-day operations, maintenance, radiation shielding, spare parts and hardware costs. The Moon
  timeline comes next.

Prepare the Moon data (see [data/README.md](data/README.md) §7):

```bash
(cd backend && uv run --with pyshp python ../scripts/moon/prepare_moon_reference.py)
```

```bash
(cd backend && uv run python ../scripts/moon/prepare_moon_elevation.py)
```

To add a body, add it to both registries, add a `src/<body>/` workspace, and serve its data under
`/api/<body>`. The H3 layer format in `data/prepared/moon/h3/layers.json` is the template for new
per-cell layers such as sunlight, temperature, ice and composition.

## Layout

```
docker-compose.yml        Postgres 17 + Flyway
db/migrations/            Flyway SQL migrations (V<n>__description.sql)
backend/                  FastAPI + h3-py + psycopg (managed with uv)
frontend/                 React + TypeScript + Vite, MapLibre, deck.gl, h3-js
  src/bodies/             Body registry (Earth, Moon): basemap, radius, view, credits
  src/earth/EarthApp.tsx  Earth workspace (Explore, Build, Timeline)
  src/moon/               Moon workspace (Explore, Build)
scripts/moon/             Moon data preparation (reference layers, LOLA elevation)
data/prepared/moon/       Prepared Moon layers + provenance (source.json, h3/layers.json)
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
| `GET /api/bodies` | Body registry: id, name, radius, frame, simulation resolution |
| `GET /api/cells/locate?latitude=&longitude=&resolution=6&body=earth` | Cell containing a coordinate (`body=moon` for Moon areas) |
| `GET /api/cells/{h3Id}?body=earth` | Cell geometry, area and edge length on the body, neighbours, parent |
| `GET /api/moon`, `GET /api/moon/layers/{id}` | Moon reference manifest (+ availability) and its layers: landed objects, IAU gazetteer, mare polygons, planned missions / Artemis regions |
| `GET /api/moon/keepout` | Heritage keep-out rings (geodesic on the Moon sphere) |
| `GET /api/moon/cells/{h3Id}/context` | Nearest named features, nearby landed objects, keep-out rings, mare and LAC quad for a Moon cell |
| `GET /api/moon/sources` | Moon data credits (incl. LROC WMS and H3 layer sources) |
| `GET /api/moon/h3`, `POST /api/moon/h3/{layerId}` `{cells}` | Moon H3 layers and their values for display cells (finer cells resolve to the layer's finest resolution; `null` = no data) |
| `GET/POST /api/scenarios` | List (`?body=earth` default, or `moon`) / create (`{name, body?}`) worlds |
| `GET/PATCH/DELETE /api/scenarios/{id}` | Load (with projects) / rename / delete; PATCH `assumptions` merges top-level keys (`periodDays`, `budgets`, `stress` validated) |
| `POST /api/scenarios/{id}/branch` | Branch a scenario |
| `GET /api/infrastructure[/{layer}]` | Datacenters, power plants, dams, substations, HV lines, airports, ports (region-tagged) + per-source provenance |
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
| `GET /api/building-templates` | Predefined building types (42, each with a `category`): fields, units, help; no numeric defaults |
| `GET /api/building-presets` | Real example buildings: stats and parameters with cited provenance, sources, notes and reference site (read-only) |
| `GET/POST /api/building-definitions`, `GET/PATCH/DELETE /api/building-definitions/{id}` | Saved building definitions; edits/deletes never change placed snapshots |
| `POST /api/building-assessments` | Read-only calculation + pass/fail/unknown checks for a draft at an exact `location`, or over `bounds`/`region` res-6 cells (limit 30,000, else 422); graded site suitability (`suitability`, per-cell `tier`/`grades`) for types with a profile |
| `POST /api/scenarios/{id}/evaluate` `{stress?, periodDays?, budgets?}` | Unstressed vs stressed per-building results, pooled budgets and totals |
| `GET /api/scenarios/{id}/timeline` | Daily project emissions/resource totals and dated PM2.5/PM10 baselines for the local timeline display |

Interactive docs: http://localhost:8000/docs

## Coordinate contract

- Stored locations: `latitude`, `longitude` (WGS84 degrees, `double precision`), longitude normalised to [-180, 180).
- Moon coordinates are planetocentric in the IAU_2015:30100 Mean-Earth frame (R = 1737.4 km), longitude positive
  east, normalised to [-180, 180). Upstream 0–360 longitudes are converted on ingest.
- H3 IDs are lowercase hex **strings** everywhere (JS, JSON, DB). They are never converted to numbers.
- Simulation resolution is fixed at 6. Changing the display resolution never changes a project's cell.

## Known limitations

- Web Mercator projection: latitudes beyond about ±85° are not displayed (cells exist, the map can't show them).
  A globe projection is a later option once tested with the H3 overlay. On the Moon this hides the core of the
  south-pole Artemis area (Shackleton is at 89.9°S). Those records are listed and selectable, and a polar inset is
  the planned fix (catalogue §2.3).
- Moon tiles come from the live LROC Lunaserv WMS, at about 1 s per tile. Self-hosted PMTiles are the planned
  replacement (catalogue MOON-MAP-02).
- `highPrecision` hexagon rendering is on. The ~5,000 cell budget has not been benchmarked on the demo laptop yet.
