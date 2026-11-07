# CLAUDE.md — Project overview

Last reviewed: 2026-11-07  
Working project name: **New Worlds** (placeholder; no final brand has been chosen).  
Stage: planning a two-person, 24-hour hackathon build. This document is a specification, not a statement that features or integrations already exist.

Read [CLAUDE.mapping.md](./CLAUDE.mapping.md) before implementing the map or spatial model. Read [CLAUDE.data-sources.md](./CLAUDE.data-sources.md) before implementing data ingestion, source access, attribution, or exports.

## Product intent

Build an interactive Earth exploration and scenario sandbox. Users discover resources and environmental conditions, place hypothetical projects, inspect estimated consequences, connect complementary projects, and compare alternative futures for real places.

The hackathon theme asks for a project that opens a door to unexplored data, ideas, or new possibilities. Our interpretation is: **explore the world that exists, then experiment with worlds that could exist.**

The user's central example is placing a data centre in a hexagon and seeing how its water, electricity, and material requirements affect connected locations. The entire Earth should be addressable through a consistent hexagonal grid with longitude/latitude coordinates. Kilometre-scale cells are sufficient.

The long-term ambition is broad data integration: satellite observations, geology, environmental measurements, infrastructure, and resource records. This does not imply every catalogue source will be integrated during the hackathon.

## Core user loop

1. Explore a location and turn on a data layer.
2. Inspect a cell: value, units, date, source, coverage, and limitations.
3. Place a project at an exact location inside that cell.
4. Change its size or technology assumptions.
5. View estimated demand, supply, outputs, and bottlenecks.
6. Connect compatible projects or move the project.
7. Branch the scenario and compare the two possible worlds.

Users should be able to discover useful combinations, not merely inspect a static map. Example: colocating a data centre and greenhouse could create a potential heat-reuse connection. Its usefulness depends on supplied assumptions about recoverable heat, temperature suitability, losses, and demand.

## Scope and working defaults

These defaults make the build concrete. They are implementation recommendations, not additional requirements confirmed individually by the user.

| Area | Working default |
| --- | --- |
| Team / deadline | Two developers, 24 hours |
| Frontend | React, TypeScript, Vite |
| Spatial system | H3 through h3-js v4 |
| Simulation cell size | H3 resolution 6 |
| Map | MapLibre GL JS with a licensed tiled basemap |
| Hex rendering | deck.gl H3HexagonLayer |
| Initial project types | Data centre, solar generation, greenhouse |
| Initial metrics | Electricity, freshwater demand, construction-material demand from a declared bill of materials, occupied land, usable/recoverable heat |
| Baseline | Selected real datasets with provenance; preprocessed subsets for the demo |
| Simulation | Small deterministic resource-accounting model |
| Coverage | Globally navigable grid; calculations only where inputs exist or assumptions are explicitly provided |
| Persistence | Local scenario JSON/local storage initially; optional small API and database |
| AI | Optional explanation/search assistance; never the source of numerical simulation truth |

Do not treat low-detail or missing data as a reason to draw fabricated global measurements. The map should remain navigable everywhere, with unavailable measurements clearly marked.

## Minimum viable demonstration

Must work:

- Navigate the world and inspect stable H3 cells.
- Show at least two useful measured/modelled baseline layers with source metadata.
- Place, edit, move, and remove a project.
- Calculate reproducible changes from the project's explicit parameters.
- Show baseline, scenario, and difference views where comparisons are meaningful.
- Create two scenarios from the same baseline and compare their outputs.
- Save and reload a scenario without shifting projects or changing results.
- Keep the demo functional if an upstream data API is temporarily unavailable.

Recommended if time permits:

- Connect a data centre's recoverable heat to greenhouse heating demand.
- Add solar generation and display the resulting electricity balance over a specified period.
- Add one stress control, such as reduced water allocation or reduced solar output.
- Include a prepared mineral observation layer to retain the original material-exploration identity.

Do not make launch depend on a paid imagery contract, delayed account approval, custom mineral-detection model, live global raster processing, or licensing correspondence.

## User activities to preserve in the design

| Activity | Example |
| --- | --- |
| Discover | Identify an unusual combination of water risk, energy potential, land cover, or known resources |
| Place | Add a data centre or greenhouse at a real coordinate |
| Configure | Change size, cooling assumptions, energy use, or heat recovery |
| Connect | Supply a greenhouse from an eligible heat-producing project |
| Relocate | Compare the same project at two locations |
| Search | Rank candidate cells using explicitly selected criteria |
| Branch | Compare conventional and alternative project configurations |
| Stress-test | Reduce an assumed supply and inspect unmet demand |
| Invent | Explore a hypothetical efficiency improvement |
| Restore | Remove a project or change land-use assumptions |
| Challenge | Meet a demand target within a water or land budget |

Search, invention, restoration, and elaborate challenges are extensions unless the core loop is already complete. Candidate rankings describe the selected criteria; they do not establish planning permission, grid access, or commercial feasibility.

## Simulation meaning and resource accounting

The model must distinguish:

- **Stock:** a quantity available at a point in time.
- **Flow:** a quantity per unit time.
- **Capacity:** a maximum rate or storage limit.
- **Risk/index:** a dimensionless assessment, not a physical inventory.
- **Observation:** a measured or retrieved quantity.
- **Scenario assumption:** a user-selected hypothetical input.

Use one explicit time interval per calculation. Track electricity in kWh per interval, power in kW, water in m³ per interval, area in m², heat in kWh per interval, and material quantities in kg or tonnes with a stated basis.

For a simple data-centre model:

- IT energy = IT power × operating time × load fraction.
- Facility energy = IT energy × PUE.
- Water demand = energy on the declared WUE basis × WUE, with units converted.
- Recoverable heat = eligible energy × declared recovery fraction.
- Delivered useful heat must account for suitability and transfer losses and cannot exceed the receiver's demand.

Do not hardcode unsupported “typical” coefficients as facts. Each coefficient needs a cited source or an explicit `user_assumption` / `demo_assumption` label. State whether WUE uses IT energy or whole-facility energy.

Solar generation requires an irradiation period and conversion assumptions. Annual solar yield cannot prove hourly supply continuity. A battery extension needs a state-of-charge model and charge/discharge limits.

Do not infer usable water supply from soil moisture, lake colour, annual precipitation, or a water-stress score. If actual allocated water availability is unknown, report added demand and contextual risk. A hypothetical supply budget is allowed only when labelled as an assumption.

Construction materials are usually one-time project inputs; operating demands recur. Do not deduct copper from neighbouring ground because a building was placed there. Resource sourcing is a separate relationship.

## Spatial effects and connections

H3 adjacency supports nearby searches and display. It is not a physical propagation model.

- Water impacts follow declared sources, catchments, abstraction/discharge relationships, and allocations.
- Electricity effects follow a simplified supply network and its declared capacity.
- Material demand can connect to distant suppliers.
- Heat reuse requires a viable connection and explicit delivery assumptions.
- Air pollution follows a transport model if implemented; a coloured radial halo alone is not a validated plume.

For the hackathon, use explicit user-defined links and a transparent allocation rule. Show unmet demand instead of creating negative supplies. Prevent double-counting the same supplier output across multiple recipients.

## Data and evidence requirements

Every displayed numeric layer needs:

- Variable name and scientific meaning.
- Value and units, including depth/altitude where relevant.
- Observation period and publication/retrieval date.
- Source/product/version and upstream record identifiers.
- Native spatial resolution or support geometry.
- Aggregation method and coverage.
- Quality flags and uncertainty when available.
- Licence, attribution, and permitted display/export status.
- Evidence type: satellite retrieval, in-situ sample, reported record, model output, or scenario assumption.

Missing values are null, never zero. Distinguish missing coverage, rejected quality, below-detection results, and model failures. Avoid smoothing sparse samples into a continuous “measured” surface.

Satellite mineral signatures describe exposed surface material. They do not establish buried ore tonnage, reserve value, or concentration by mass. A geological occurrence record and a measured assay are different layers.

The baseline remains immutable. Scenario changes are stored separately and reference a baseline revision and model version.

## UI priorities

- Map remains visible while interacting with the inspector.
- Layer selector groups data by subject and evidence type.
- Display a clear legend with units and missing-data styling.
- Cell inspector exposes provenance and model assumptions.
- Project editor uses understandable units and labels.
- Comparison view shows absolute values and changes with consistent scales.
- Distinguish illustrative estimates from observations without overwhelming the interface.
- Keep map attribution visible.
- Avoid calling a synthetic result “satellite-detected” or “real time.”

The “show me something interesting” feature may describe combinations actually present in loaded data. It must cite the relevant layers and avoid implying statistical significance from a visual coincidence.

## Suggested work division and sequence

Developer A: map, viewport cell generation, picking, placement, scenario controls.  
Developer B: source adapters, small data fixtures, unit-normalisation, model calculations, provenance.

Suggested order:

1. Agree on H3 resolution, coordinate order, units, shared types, and one demo region.
2. Build map + click-to-cell + persistent project placement.
3. Add a small number of preprocessed baseline layers.
4. Implement project accounting and a comparison view.
5. Add one connection and one stress control.
6. Verify data semantics, boundary behaviour, and demo recovery.
7. Prepare a short end-to-end demonstration.

## Acceptance checks

- Same coordinates and H3 resolution produce the same cell ID everywhere.
- A saved project retains its exact coordinates after reload and map zoom changes.
- No fine-resolution whole-Earth enumeration occurs in the UI.
- Changing display resolution does not change the simulation.
- Scenario outcomes are reproducible from saved inputs.
- Supply is not double-counted and resource balances do not create energy or water.
- Unknown baseline quantities remain unknown.
- Each dataset has visible provenance and valid rights for the intended use.
- Globe/date-line edge cases are handled or clearly bounded before the demo.
- At least one scenario can be completed using cached/prepared inputs.

## Deferred work

Custom hyperspectral classification; global live ingestion; economic forecasting; detailed hydrological/grid/atmospheric simulation; permitting analysis; all commercial imagery; automatic supplier selection; polished multiplayer collaboration.

Before expanding scope, complete the demonstration loop. The catalogue is an integration backlog, not a claim that the current build contains every listed source.
