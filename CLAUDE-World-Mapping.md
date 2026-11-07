# CLAUDE.mapping.md — World map and H3 implementation plan

Last reviewed: 2026-11-07  
Status: proposed implementation specification for a two-person, 24-hour hackathon.

Read [CLAUDE.md](./CLAUDE.md) for product scope and simulation meaning. Source access and licensing are in [CLAUDE.data-sources.md](./CLAUDE.data-sources.md).

## 1. Architecture

Treat these as independent components:

| Component | Responsibility |
| --- | --- |
| Basemap tiles | Detailed coastlines, roads, settlements, buildings, water and labels |
| MapLibre GL JS | Map camera, projection, navigation and basemap rendering |
| h3-js | Geographic cell indexing, boundaries, neighbours and resolution hierarchy |
| deck.gl H3HexagonLayer | Display and picking of selected H3 cells |
| Baseline data adapters | Map source measurements or records to cells without losing provenance |
| Scenario model | Calculate hypothetical changes from explicit parameters |
| Scenario overlay | Display changes without mutating the baseline |

A detailed basemap can coexist with coarse simulation cells. Basemap detail does not improve the resolution of water, soil or mineral measurements.

Use React + TypeScript + Vite unless the team already has a functioning frontend. Pin a mutually compatible set of MapLibre/deck.gl packages in the lockfile. Use H3 v4 API names throughout; do not mix examples from H3 v3.

Primary references:

- [H3 overview](https://h3geo.org/docs/core-library/overview/)
- [h3-js](https://github.com/uber/h3-js)
- [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/)
- [deck.gl with MapLibre](https://deck.gl/docs/developer-guide/base-maps/using-with-maplibre)
- [H3HexagonLayer](https://deck.gl/docs/api-reference/geo-layers/h3-hexagon-layer)

## 2. Grid choice and coordinate contract

Use H3 as the shared spatial index. H3 defines the global grid algorithmically; there is no need to download a world grid shapefile or pre-create a database row for every cell.

Alternatives:

- S2 has quadrilateral cells and exact geometric hierarchical subdivision. It is useful when that property matters more than a hexagonal interface.
- Geohash uses rectangular geographical bins.
- A custom flat hex grid creates unnecessary projection, seam and polar work for this deadline.

Reference: [S2 cells](https://s2geometry.io/devguide/s2cell_hierarchy), [H3 introduction](https://h3geo.org/docs/).

Use this coordinate contract:

| Context | Representation |
| --- | --- |
| Persistent project location | Named `latitude` and `longitude` fields in WGS84 degrees |
| GeoJSON / MapLibre / deck.gl position | `[longitude, latitude]` |
| `h3.latLngToCell` | `(latitude, longitude, resolution)` |
| `h3.cellToLatLng` | `[latitude, longitude]` |
| `h3.cellToBoundary(id, true)` | Closed GeoJSON-order boundary ring |
| H3 ID in JS, JSON, database/API | String; do not convert to a JavaScript Number |

Validate latitude in [-90, 90] and normalise longitude consistently to [-180, 180). Preserve exact project coordinates separately from cell centres. Reproject national coordinate systems, such as EPSG:27700, before H3 indexing.

Reference: [H3 indexing functions](https://h3geo.org/docs/api/indexing/).

## 3. Resolution

Canonical simulation resolution: **6**.

| Resolution | Average hexagon area | Approximate flat-to-flat width | Global cell count |
| --- | ---: | ---: | ---: |
| 5 | 252.9 km² | 17 km | 2,016,842 |
| 6 | 36.1 km² | 6.5 km | 14,117,882 |
| 7 | 5.16 km² | 2.4 km | 98,825,162 |

Widths are rough regular-hexagon estimates, not guaranteed cell dimensions. Actual areas vary. Calculate the actual area of a cell when computing density or totals. H3 contains 12 pentagons at every resolution. A boundary can have additional vertices where it crosses projection faces; do not force every returned ring to six points.

Source: [H3 cell statistics](https://h3geo.org/docs/core-library/restable/), [h3-js boundary API](https://github.com/uber/h3-js#h3celltoboundaryh3index-formatasgeojson--arraycoordpair).

Use display level of detail:

| View scale | Initial display resolution |
| --- | --- |
| World | 1–2 |
| Continent / large country | 3–4 |
| Region | 5 |
| Local exploration | 6 |

These are heuristics. Choose resolution from estimated screen density and a cell budget, not zoom alone. Start with a target of roughly 5,000 visible cells and benchmark on the demonstration laptop. This is a performance target, not a measured guarantee.

Do not change the simulation resolution as the user zooms. Project placement should zoom to local view or explicitly select the resolution-6 cell containing the click.

## 4. Basemap and projection

Default basemap: OpenFreeMap, for example:
`https://tiles.openfreemap.org/styles/liberty`

Use the current [OpenFreeMap quick start](https://openfreemap.org/quick_start/), including the worker setup appropriate to the installed MapLibre version. Preserve attribution. OpenFreeMap provides map context, not mineral or water-availability measurements.

Optional satellite background: MapTiler or another licensed provider. Do not assume Google Maps imagery can be copied into a custom map. Use the provider's supported tiles and plan.

Global coverage must include a deliberate polar strategy:

- A normal Web Mercator map does not show the poles.
- MapLibre supports a globe projection, and current deck.gl documentation describes globe integration.
- Test the chosen package versions with H3 overlays before investing in globe styling.
- At whole-world scale, let the renderer clip a coarse global grid to the visible hemisphere.
- If the initial prototype uses Mercator, explicitly record its polar viewing limitation; do not claim literal complete polar display.

References:

- [MapLibre globe example](https://maplibre.org/maplibre-gl-js/docs/examples/display-a-globe-with-a-vector-map/)
- [deck.gl release documentation](https://deck.gl/docs/whats-new)
- [MapTiler satellite layer](https://docs.maptiler.com/schema-raster/satellite/)

## 5. Generate only what needs to be displayed

World overview:

- Resolution 2 has 5,882 cells.
- Generate this small set once from resolution-0 cells and their resolution-2 children.
- Display it as an overview; missing data remains missing.
- Never enumerate all resolution-6 or resolution-7 cells in the browser.

Regional/local view:

1. Wait for `moveend` or debounce camera movement.
2. Determine a visible ground footprint or conservative bounded region.
3. Estimate the cell count before generating it; coarsen first if over budget.
4. Split the query at the date line where required.
5. Obtain cell IDs with `polygonToCells` and include an edge margin.
6. Deduplicate cells and validate the selected resolution.
7. Fetch or calculate layer values in one batch.
8. Ignore/cancel stale requests using an AbortController or request generation ID.
9. Render and cache by layer, source revision, time and resolution.

`polygonToCells` normally includes cells whose centres lie in the polygon. A buffered query or a neighbouring-cell expansion is needed for cells that cross the viewport boundary. For globe views near the horizon, prefer a conservative cover and renderer clipping. If a fine cover cannot be bounded safely, retain the coarse overview until zoomed closer.

Do not pass a world-spanning, unbounded or inverted polygon into fine-resolution enumeration. A view crossing 180° must become two valid regions or a deliberately unwrapped/split geometry.

Use a Web Worker for cell generation and data transforms if they interrupt interaction. Reuse geometry/cell-ID sets while only colours change.

Reference: [H3 region functions](https://h3geo.org/docs/api/regions/).

## 6. Basic H3 operations

Illustrative TypeScript using H3 v4:

```ts
import {
  latLngToCell,
  cellToLatLng,
  cellToBoundary,
  gridDisk,
  cellArea,
  UNITS,
} from "h3-js";

export const SIMULATION_RESOLUTION = 6;

export function inspectLocation(latitude: number, longitude: number) {
  const h3Id = latLngToCell(latitude, longitude, SIMULATION_RESOLUTION);

  return {
    h3Id,
    centreLatLng: cellToLatLng(h3Id),
    boundaryLngLat: cellToBoundary(h3Id, true),
    areaKm2: cellArea(h3Id, UNITS.km2),
    neighbours: gridDisk(h3Id, 1).filter(id => id !== h3Id),
  };
}
```

`gridDisk(id, 1)` includes the original cell. Do not assume a fixed neighbour count around pentagons. Grid distance counts cell steps; it is not a fixed distance in kilometres.

## 7. Rendering and interaction

Use `H3HexagonLayer` for the visible cell array. Keep a layer at one display resolution. Suggested settings:

- `pickable: true`
- `filled: true`
- `stroked: true`
- `extruded: false` initially
- `highPrecision: true` initially, with a visible-cell budget
- `getHexagon: row => row.h3Id`
- `getFillColor` from the selected layer's legend and missing-data status

Use the MapLibre integration appropriate to the installed deck.gl version. Do not copy an outdated overlay import without checking compatibility.

Interactions:

- Hover: lightweight tooltip with value, units and date.
- Click: selected-cell inspector.
- Project placement: clicked exact coordinate plus canonical H3 ID.
- Layer switch: retain the camera and selected project.
- Scenario switch: retain the baseline revision and compare matching periods.
- Missing data: transparent/neutral styling, not the minimum colour on the numeric scale.
- Difference view: diverging scale centred at zero, with consistent comparison limits.

Render projects as separate points/icons; cell colour is not a building footprint. Store footprint geometry only if the user explicitly defines it.

Do not move coastal cells to fit land. Keep their canonical H3 geometry and calculate land/water fractions separately. A centre-point land mask alone can miss islands and misclassify coastal cells.

## 8. Storage model

No polygon column is required for the first prototype; derive cell boundaries from IDs.

```ts
type Project = {
  id: string;
  scenarioId: string;
  type: "data_centre" | "solar" | "greenhouse";
  latitude: number;
  longitude: number;
  h3Id: string; // resolution 6
  parameters: Record<string, number | string | boolean>;
};

type CellObservation = {
  h3Id: string;
  layerId: string;
  value: number | null;
  unit: string;
  timeStart: string | null;
  timeEnd: string | null;
  sourceId: string;
  productId: string;
  sourceVersion: string;
  sourceSupportId: string | null;
  nativeResolution: string;
  aggregation: string;
  coverageFraction: number | null;
  evidenceType:
    | "satellite_retrieval"
    | "in_situ"
    | "reported"
    | "modelled"
    | "scenario_assumption";
  status: "valid" | "no_data" | "quality_rejected" | "below_detection";
  licenceId: string;
};

type Scenario = {
  id: string;
  parentScenarioId: string | null;
  baselineRevision: string;
  modelVersion: string;
  projects: Project[];
  connections: Array<{
    fromProjectId: string;
    toProjectId: string;
    resource: string;
    capacityPerInterval: number;
    unit: string;
    lossFraction: number;
  }>;
  assumptions: Record<string, unknown>;
};
```

Extend observations for uncertainty, qualifiers, sample depth, detection limits, original geometry, source URL and provenance. A numeric null plus status is preferable to silently coercing missing values to zero.

Suggested cache key:
`layerId + sourceVersion + period + depth + resolution + h3Id + aggregationVersion`

A scenario is a set of changes and assumptions over an immutable baseline, not a cloned global database.

## 9. Bringing source data into H3

### Points

Index points using their actual coordinates. Preserve source record IDs, time, units and qualifiers. Do not average different chemical species, sample media or depths together.

### Rasters

Read relevant windows from numerical assets (COG, NetCDF, Zarr or HDF as appropriate). Reproject footprints correctly, mask invalid values, apply scale factors and units, then aggregate.

- Temperature or similar intensive values: appropriate area-weighted statistics.
- Counts/volumes: preserve totals; use overlap fractions if splitting source pixels.
- Densities: integrate over area before summing, then divide if a density is needed.
- Categorical land cover: class fractions or an explicitly stated dominant class.
- Sparse observations: retain coverage and sample count.
- Coarse model fields: keep the native support ID so many H3 cells do not become fictitious independent observations.

A coloured PNG/WMS image is not a numerical raster suitable for resource calculations.

### Polygons and networks

Intersect source polygons with cells when exact overlap matters. Preserve catchment IDs, national boundaries, plant IDs and network topology. Cell adjacency does not replace those relationships.

### Multiple resolutions

H3 logical child-to-parent aggregation is useful for display, but it is not exact polygon nesting. Choose and document one policy:

- logical hierarchy for fast overview summaries;
- actual geometry intersections for exact regional area accounting.

Do not mix these policies silently. Recompute appropriate statistics, not just means of means. Keep sufficient statistics such as valid area and weighted sums where needed.

Reference: [H3 indexing and containment](https://h3geo.org/docs/highlights/indexing/).

## 10. Proposed application API

These are routes we would implement in our application. They are not upstream provider endpoints.

| Route | Purpose |
| --- | --- |
| `GET /api/layers` | Layer catalogue, units, source, licence, coverage and display settings |
| `GET /api/layers/:layerId/cells?bbox=west,south,east,north&resolution=6&time=...` | Bounded batch of cell values |
| `GET /api/cells/:h3Id` | Detailed observations and provenance for a selected cell |
| `POST /api/scenarios` | Save a new scenario or branch |
| `GET /api/scenarios/:id` | Restore a saved scenario |
| `POST /api/scenarios/:id/evaluate` | Evaluate explicit inputs against a pinned baseline |
| `GET /api/sources` | Provider references and attribution |

The backend validates the requested resolution, cell budget, date, layer and spatial extent. Responses return the effective resolution and source revision. Split date-line requests client-side or explicitly support them in the API contract.

For the 24-hour prototype, these interfaces can be local functions backed by prepared JSON. Move behind HTTP only when useful. Keep secret credentials and unrestricted tokens out of browser code and scenario exports. A provider's deliberately public, domain-restricted map key may be used in the browser under that provider's documented rules.

## 11. Physical influence is separate from the grid

Use nearby cells for discovery and highlighting. Do not implement physical effects as automatic equal decrements to the six neighbours.

Maintain explicit connections for electricity, water, heat and material flows. Use declared losses, capacity and allocation rules. If a radial highlight is purely illustrative, label it as such.

Examples:

- A project's water demand can be attributed to its connected source/catchment.
- A material requirement can reference a distant supplier.
- A known power station's capacity is not proof of spare grid capacity at the project.
- A water-stress score cannot be reduced by a water volume without a compatible underlying model.

## 12. Build milestones and validation

Milestone A:

- Basemap loads with attribution.
- Click-to-cell works.
- Exact project location persists.

Milestone B:

- Coarse global overview and bounded local cells.
- Smooth camera movement and stale-request handling.
- Date-line and polar behaviour verified.

Milestone C:

- Real numerical data joins by H3.
- Missing values, units and provenance visible.
- One project changes a scenario layer without editing the baseline.

Milestone D:

- Branch/compare/save/reload.
- One connected-resource interaction.
- Cached demonstration works without a live provider request.

Targeted checks:

- Test known coordinates in both hemispheres and at negative longitude.
- Test immediately on either side of ±180° and near the poles.
- Test at least one pentagon neighbourhood.
- Test cell boundary pick consistency.
- Verify totals survive aggregation where the quantity is additive.
- Verify changing display resolution leaves scenario totals unchanged.
- Verify invalid units and missing baseline values do not become plausible-looking results.
- Benchmark the selected cell budget on the actual laptop.

## 13. What this file does not claim

No mapping code has been implemented or benchmarked by creating this document. Package compatibility, rendering edge cases and data access must be exercised in the actual repository. Global addressability is a geometry feature; complete global measurements are a separate data-coverage problem.
