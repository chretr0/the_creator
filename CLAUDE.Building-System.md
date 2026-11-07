# Building definition, placement and scenario stress testing

Date: 2026-11-07. Status: implementation specification, not a statement that these features already work.

Implement this functionality inside the existing New Worlds repository. Extend the current React/TypeScript map, FastAPI backend and PostgreSQL scenario/project system. Do not create a separate application or replace the existing exploration workflow.

Read [CLAUDE-Project-Overview.md](./CLAUDE-Project-Overview.md), [CLAUDE-World-Mapping.md](./CLAUDE-World-Mapping.md) and [CLAUDE-Data-Sources.md](./CLAUDE-Data-Sources.md) for the existing spatial, evidence and data contracts. This document specifies the building workflow; it does not request every future feature in those companion documents. Use the actual repository to establish implementation status because some planning documents predate the current code.

## 1. Agreed feature scope

The team's supplied handwritten notes specify:

- Define a building, then build it.
- Offer predefined buildings, explicitly including power stations and water plants, with costs.
- Let users define building statistics: raw-material usage, power usage, area/footprint, water, air quality, light pollution and worker capacity.
- Users describe what they want to build; the application shows where it is possible.
- Provide scenario controls for stress testing.

Everything below makes those requirements implementable. Field names, units, API routes, suitability states, database structure and the initial stress controls are **implementation defaults**, not additional product decisions attributed to the team. Keep these defaults small and consistent with the existing architecture. Do not add unrelated product features.

Here, "build" means placing a hypothetical building in a saved scenario. "Possible" means meeting the criteria that were actually evaluated using identified data and assumptions. It does not establish planning permission, ownership, engineering feasibility or a utility connection.

## 2. Current implementation to extend

At the time of writing:

| Existing code | Role and required extension |
| --- | --- |
| `frontend/src/lib/projectTypes.ts` | Field definitions for `data_centre`, `solar` and `greenhouse`; extend with the common building statistics and new types. |
| `frontend/src/lib/api.ts` | Project/scenario types and API client; update contracts together with the backend. |
| `frontend/src/components/ProjectEditor.tsx` | Editing names, types, coordinates and scalar assumptions; extend to the building form and structured statistics. |
| `frontend/src/components/ScenarioPanel.tsx` | Existing scenario and project lists; extend with scenario controls and results. |
| `frontend/src/App.tsx` | Placement/move/inspect modes, active scenario and selected project; integrate define, assess and build states. |
| `frontend/src/components/WorldMap.tsx` | Map picking, project markers and H3 overlays; reuse for placement previews and suitability display. |
| `backend/app/models.py` | Pydantic models currently limit project types to three values and parameters to scalar values. |
| `backend/app/routers/scenarios.py` | Project CRUD and scenario branching; preserve these behaviours when extending persistence. |
| `backend/app/layers.py`, `h3store.py`, `features.py` | Existing local data registries, H3 lookups and prepared feature queries; use these for assessment. |
| `backend/app/routers/layers.py`, `features.py` | Existing data endpoints and cell profiles. |
| `db/migrations/V1__scenarios_and_projects.sql` | Existing scenario/project tables, JSONB assumptions/parameters and a restrictive project-type CHECK constraint. |

Do not assume a new project type works after changing only a dropdown: update the database constraint, Python literal/validation, TypeScript union, type registry, map styling, editor and serialization paths together. Inspect the repository again before choosing migration numbers or adding files.

## 3. User workflow

1. Select or create a scenario.
2. Choose **Define building**. Start from a predefined type or a custom definition.
3. Give it a name and a plain-language description of what the user wants to build.
4. Review its editable statistics, costs and location requirements. Unknown fields can remain blank.
5. Choose an assessment area, initially the current map view or one of the existing prepared regions, and choose **Find locations**.
6. Show candidate locations on the map, with an explanation of each evaluated requirement and any missing evidence.
7. Select a candidate or inspect an exact map location. Show a placement preview and its assessment.
8. Choose **Build here** to create one building in the active scenario. Cancel creates nothing.
9. Select the building to review its statistics, calculated usage and costs; edit, move or delete it through the existing workflow.
10. Open scenario controls, change a stress assumption and inspect how results change against the same scenario's unstressed calculation.

Keep the map visible throughout. Preserve layer browsing, cell inspection, current project selection and scenario switching. Escape should cancel preview/placement/move mode without discarding a saved building.

The description is part of the saved definition. It is not a reliable source of numerical values by itself: use the reviewed structured fields for calculations. If the description is the only input, show which requirements need to be supplied before an assessment can be conclusive. Do not invent values or silently infer them from wording.

## 4. Definitions, templates and placed buildings

Use three distinct concepts:

- **Predefined template:** a type with a label, description, field definitions and any documented defaults.
- **Building definition:** the user's named, described and configured design. It can be saved and used for placement.
- **Placed building:** a project belonging to a scenario, with exact coordinates and a snapshot of the definition used to create it.

Initial predefined choices must include **Power station** and **Water plant**. Retain **Data centre**, **Solar generation** and **Greenhouse** so existing scenarios continue to work. Offer **Custom building** for users who define their own statistics.

Power stations and water plants need distinct input and output fields: consuming electricity/water and supplying electricity/water cannot be represented by one ambiguous signed number. Let the user describe the technology/process; do not assign generic thermal-plant, treatment or desalination coefficients to every instance of a broad type.

Templates should be usable as forms even when numerical values are unknown. Include field names, units and help text. Populate numerical defaults only with a cited basis or an explicit, visible `demo_assumption` label; user-entered values are `user_assumption`. Do not fill in plausible-looking typical coefficients without evidence.

Editing a saved definition affects future placements. Existing buildings retain their saved statistics unless the user edits that building. Scenario branches must remain independent of later template/definition edits.

## 5. Building statistics and costs

Use the following initial field semantics. All numerical quantities must be finite; missing is null/absent, not zero. An explicit zero is allowed when the user means none. Show source/assumption information with the field or result.

| Statistic | Editable information | Units and calculation meaning |
| --- | --- | --- |
| Raw-material usage | List of named materials, quantity and whether consumed during construction or operation | Store mass in kg; allow tonne input with explicit conversion. Construction quantities occur once; operational quantities need an explicit rate or period. |
| Power usage | Average operating demand, peak demand when known, operating hours; power-station output separately | kW for power, kWh for energy over the selected period. Peak demand is a capacity check, not an energy total. |
| Area / footprint | Occupied ground area | m²; distinguish it from a greenhouse's existing floor-area field. H3-cell area is not proof of vacant or buildable land. |
| Water | Water input demand and, for a water plant, usable output capacity; identify the water/process basis | m³/hour or m³ over a stated period. A treatment capacity is not a water abstraction allocation. |
| Air quality | Named pollutant emissions from the building, plus any user-selected baseline air-quality requirement | Emissions in kg/hour or kg/period; baseline concentrations or columns keep their original units. Do not equate emissions with a concentration change. |
| Light pollution | User-declared emitted-light proxy and operating hours | Initial simple proxy: upward luminous flux in lumens. Explain this label. It is not predicted sky brightness, illuminated area or a measured light-pollution index. |
| Worker capacity | Maximum workers the building can accommodate at one time; staffing requirement separately if supplied | Non-negative integer people. Capacity does not establish available labour, employment created or population impact. |
| Construction cost | One-time total, currency and price basis/date when known | Explicit ISO currency; separate from operating expenses. |
| Operating costs | Fixed cost per declared period and optional per-unit resource/material prices | Currency per period, kWh, m³ or kg as applicable. Show included and unknown components. |

Raw-material lists and pollutant lists need structured records, not stringified JSON in scalar fields. Preserve a stable identifier/name, quantity, unit, basis and provenance/assumption label for each entry.

Use one scenario evaluation period. Initial implementation can use an explicit number of days with an operating-hours input capped at the period's hours. Display the period on every usage/cost result. Convert daily/hourly rates explicitly; do not silently mix annual and monthly quantities. Existing annual fields need a declared prorating assumption before being used over a different period.

Costs must not double-count an entered all-inclusive total and its itemized breakdown. Record whether an entered operating cost is the total or a fixed component. Only combine identical currencies; no implicit exchange-rate conversion. Missing prices produce a partial known cost and missing-component list, not a complete cost of zero.

## 6. Deterministic calculations

Implement the authoritative calculation service in the backend and use the same logic for preview, candidate assessment, saved buildings and stress tests. Validate inputs on the server as well as in the form.

For direct-rate inputs:

- Operating electricity demand = average demand in kW × operating hours.
- Operating water demand = water-input rate in m³/hour × operating hours.
- Operating material demand = declared material rate × its matching duration.
- Operating pollutant emissions = pollutant emission rate × operating hours, reported separately by pollutant.
- Power output energy = declared average output in kW × operating hours. If only rated capacity is supplied, require a declared utilization/capacity assumption before calculating energy.
- Water output = declared usable-output rate × operating hours, with required input water and electricity also accounted for.
- Construction material/cost totals are counted once for each placed building, independent of operating hours.
- Resource cost = calculated quantity × a compatible unit price, where both are known.

Retain the existing type-specific parameters. For a data centre, when IT power, load fraction and PUE are supplied, facility energy = IT power × load fraction × hours × PUE. Water use from WUE must use its explicit IT/facility-energy basis and convert litres to m³. Use either these derived demands or a user-entered direct total, with a visible selected basis; never sum both. Do not discard existing greenhouse/solar fields during migration.

For solar, use either a declared output assumption or an explicit conversion model with the necessary irradiation period and performance inputs. Preserve the native meaning of POWER irradiation. Do not treat kWp as constant generated kW or annual irradiation as evidence of continuous power availability.

Validate non-negative quantities/costs, positive supplied area, integer worker counts, valid hours and bounded fractions; PUE must be at least 1 when supplied. Reject NaN/infinity and incompatible units. Keep unknown dependent results unknown, while still returning independent results that can be calculated.

Do not subtract construction materials from nearby mineral deposits, add pollutant mass to a satellite column, or turn a lumen value into an invented map of sky brightness. Persist assumptions separately from observed baseline layers.

## 7. Showing where a building can be placed

Translate the user's structured requirements into individual, inspectable checks. Keep a building's demand separate from the threshold the user chooses for a site: water consumption, for example, is not itself a maximum permitted Aqueduct score.

Initial checks can cover:

- Declared usable area versus footprint.
- Declared connected power capacity and period energy budget versus demand.
- Declared allocated water budget versus input demand.
- Declared material quantities/budgets versus construction and operating requirements.
- A user-entered construction/operating budget versus the corresponding calculated cost.
- User-selected limits for available environmental context, such as slope, land-cover class, water stress or a named air-quality variable.
- Worker capacity versus a declared staffing requirement, and declared lighting/emission limits versus matching building statistics.

Only activate checks with defined semantics and a compatible data source or explicit assumption. Associate site-specific assumptions with a candidate/location; never silently use one site's allocation at all locations. Regional shared budgets need an identified scope and accounting that includes existing buildings in that scope. Exclude the current instance when reassessing a moved/edited building to avoid counting it twice.

For each check return `pass`, `fail` or `unknown`, with the actual value, required value, units, period, source/assumption and explanation. Overall states:

| State | Rule | User-facing meaning |
| --- | --- | --- |
| `meets_criteria` | All enabled required checks pass and at least one was evaluated | Meets the evaluated criteria under the displayed assumptions. |
| `fails_criteria` | At least one required check fails | Does not meet the listed criteria; show the failures and any other unknowns. |
| `insufficient_data` | No required check fails, but at least one is unknown, or no meaningful check was enabled | More information is needed. |

Show these states with text/legend as well as colour. A user must be able to inspect unknown locations and place a hypothetical building there with its assessment visibly retained; assessment failure is not a reason to forbid scenario experimentation. Invalid input still prevents saving.

Assess resolution-6 cells only within the requested bounded area. At distant zoom levels, ask for a smaller area or a prepared-region selection rather than enumerating the world. Candidate-cell assessments are screening results at their stated spatial support; re-evaluate the exact clicked location, including point-in-basin checks, before placement. Do not colour a whole cell as proof that every parcel within it is suitable.

Return a bounded candidate list plus map results and per-check explanations. A transparent initial ordering is meets criteria, insufficient data, then fails criteria, with a stable cell-ID tie-break. Do not introduce an opaque suitability percentage. Retain the active definition and criteria while moving between candidates.

## 8. Available data and its limits

Read the current layer/feature registries and actual file availability, not only source manifests. A downloaded NetCDF or GeoTIFF does not automatically have an app adapter. Reuse local prepared data and avoid one network request per candidate cell.

| Existing source | Appropriate building-workflow use | Must not be inferred |
| --- | --- | --- |
| WorldCover, Copernicus DEM, GHSL built-up | Land-cover, elevation/slope and settlement context | Parcel vacancy, land ownership, permission or exact usable site area |
| Aqueduct, HydroBASINS/HydroRIVERS | Water-risk and catchment context | Allocated water volume or permission to withdraw it |
| POWER | Irradiation and climate context for explicit calculations | Guaranteed electricity supply or grid headroom |
| OSM power infrastructure and existing facilities | Locations and any actually reported attributes | Spare capacity or a connection available to this project |
| GHSL/WorldPop population | Population context | Available or qualified workers |
| MRDS and EMIT | Occurrence and exposed-surface mineral context | Recoverable material inventory, ore grade or a nearby supplier |
| CAMS and Sentinel-5P | Selected concentration/column context after a compatible adapter is available | A building's incremental ground-level pollution without a dispersion model |
| Water-quality observations, SMAP/GRACE/SWOT | Sample-specific quality or moisture/storage/surface-water context | Usable industrial water supply |

Do not make the building workflow depend on integrating the entire data catalogue. Start with the registered layers and explicitly entered site assumptions. Report unavailable variables as unknown and leave room for later data adapters without fabricating values. No usable light-pollution baseline or workforce-availability dataset is established by this repository audit; keep these checks assumption-based until an actual compatible source is implemented.

Store the exact source release/slice, period and spatial support used for each evaluated condition. Do not let zoom level change numerical simulation results. Keep H3 IDs as lowercase hex strings in APIs and PostgreSQL, and use the existing resolution-6 spatial contract.

## 9. Placement and editing

Before confirming placement, show the building's name/type, footprint value, major demands/outputs, known costs, candidate coordinates and suitability explanation. A marker/ghost preview is sufficient; do not treat an H3 hexagon or a marker's screen radius as the building's physical footprint.

`Build here` persists the definition snapshot and exact latitude/longitude in the active scenario. The server computes the resolution-6 cell. Prevent duplicate submission while a request is pending and retain the draft on error.

After placement, keep selection and map display consistent with the saved response. Moving preserves all building inputs and recomputes location-dependent results. Editing statistics recomputes dependent results; deleting removes the building from totals. Do not round-trip display-rounded coordinates when only editing a name or statistic.

Switching scenarios must not accidentally save a draft into the newly selected scenario. Cancel pending placement or explicitly bind its submission to the scenario for which the preview was generated. Reject stale assessment results in the UI when the definition, location, criteria or scenario inputs have changed.

## 10. Scenario controls and stress tests

Extend the existing scenario assumptions. Preserve branching, renaming, deletion and saved projects.

Initial stress controls are explicit multipliers applied to declared inputs:

| Control | Target | Neutral value |
| --- | --- | --- |
| Water availability | Declared water-supply/allocation budget | 1.0 |
| Power availability | Declared connected power/energy budget, with capacity and energy bases kept distinct | 1.0 |
| Operating demand | Declared operating resource-demand rates | 1.0 |
| Operating resource prices | Declared unit prices, not one-time construction quantities | 1.0 |

Supply multipliers range from 0 to 1 for the initial reduction tests; demand and price multipliers are finite and non-negative. Display their percentage meaning. A multiplier on unknown supply remains unknown. Disable an inapplicable control or explain why it has no calculable effect.

Calculate unstressed and stressed results against the same buildings, time period, source versions and site assumptions. Show per-building and scenario totals for electricity/water demand, declared supply, unmet demand, relevant costs and assessment-state changes. Show material use, emissions, lighting assumptions and worker capacities with their appropriate units; do not collapse unrelated pollutants or lighting outputs into one environmental score.

For comparable declared quantities, unmet demand = max(0, demand - available supply). Never create negative remaining supply or allocate the same shared supply twice. Aggregate pooled budgets once within their declared scope; do not invent per-building allocation priority. Do not automatically connect a new power station or water plant to every nearby building: output becomes a supply budget only through an explicit user-declared scope/availability assumption. Distinguish gross production from net usable output so a plant's own consumption is counted once.

Changing operating demand does not multiply construction materials, footprint or worker capacity. Emissions/light output only change if their declared formula or operating duration changes; report fixed assumptions as fixed. Stressing water availability does not alter Aqueduct values or satellite observations.

Reset restores neutral multipliers without deleting buildings or baseline inputs. Persist controls with the scenario. Branching copies inputs and controls, and subsequent changes affect only the branch. Evaluation results must identify the model/schema version and the inputs/source slices that produced them; invalidate or recompute stale results.

## 11. Persistence and API contract

Use new additive Flyway migrations. Never edit applied `V1` or reset the database to introduce this feature. Inspect the highest existing migration version first.

Implementation defaults:

- Add a persisted building-definition record with ID, name, description, type, optional template ID/version, schema version, structured statistics, criteria, provenance and timestamps.
- Extend each existing project with a versioned building-definition snapshot and an optional source-definition reference. Keep existing project IDs, coordinates and scenario relationships.
- Keep scenario evaluation period, scoped site/resource assumptions and stress controls in validated scenario assumptions or an equivalent explicit schema.
- Preserve old scalar `parameters` and interpret legacy projects through a compatibility adapter. Missing new statistics remain unknown. Do not silently replace old user inputs with template defaults.
- If a definition is deleted, placed snapshots remain usable. Branch copies every required snapshot and scenario input; it cannot depend on mutable shared definitions.

Do not force nested material/emission/cost structures into the current `ParamValue` scalar union. Introduce explicit validated models for the new fields and synchronize Python and TypeScript contracts. Store editable inputs separately from derived results so recalculation cannot overwrite assumptions.

Suggested routes, following the current `/api` convention:

| Route | Contract |
| --- | --- |
| `GET /api/building-templates` | Supported types, schema/defaults, units and provenance. |
| `GET/POST /api/building-definitions` | List or save user definitions. |
| `GET/PATCH/DELETE /api/building-definitions/{id}` | Load, edit or remove a definition without changing existing snapshots. |
| `POST /api/building-assessments` | Read-only calculation for a draft definition and bounded cells or exact location, with scenario context and explicit criteria. |
| Existing project creation/update routes | Persist or edit placed snapshots; creation still belongs to one scenario. |
| Existing scenario update route | Save evaluation assumptions and controls. |
| `POST /api/scenarios/{id}/evaluate` | Return unstressed/stressed results and check explanations without changing source data. |

Reuse an existing equivalent route if one has appeared since this document was written. Do not require saving a temporary project to assess a candidate. Share calculation code internally rather than having the backend call its own HTTP endpoints.

Validate body size, finite coordinates, requested area/cell count and period bounds. Apply a documented server-side candidate limit, return a clear narrow-the-area response when exceeded, and never return a silently incomplete set as exhaustive. Debounce/cancel obsolete frontend requests and bind results to the relevant input revision. Avoid raw scientific-file processing in request handlers.

## 12. Implementation order

1. Inspect current models, migrations, project UI, map modes, data registries and tests. Preserve all unrelated changes in the working tree.
2. Define shared types/units and add migration plus legacy compatibility. Verify that existing projects still load and branch.
3. Implement predefined/custom definition forms and persistence, including every statistic in section 5.
4. Implement deterministic calculations and per-check pass/fail/unknown assessment with explicit input provenance.
5. Integrate bounded candidate search, map explanations and exact-location preview; connect `Build here` to existing project creation.
6. Extend instance editing/moving/deletion and refresh calculations after changes.
7. Add scenario controls, unstressed/stressed calculations, persistence and independent branching.
8. Run focused backend/frontend checks and exercise the full flow on the existing prepared regions. Report any unsupported check as unknown rather than claiming it works.

## 13. Acceptance checks

- A user can choose a power-station or water-plant template, or define a custom building, and enter all agreed statistics plus costs and a description.
- Existing data-centre, solar and greenhouse projects load, render, edit and branch without losing their original assumptions.
- A saved definition can create a placed building; editing the definition later does not silently change the placed instance.
- Blank, explicit zero and invalid input have distinct behaviour. No NaN/infinity is stored or returned.
- A deterministic calculation fixture with average demand 100 kW, 8 operating hours/day and a 10-day period yields 8,000 kWh. At 2 m³/hour it yields 160 m³. These are test inputs, not template defaults.
- One-time construction quantities/costs are counted once; changing the evaluation duration changes recurring inputs only.
- Emissions are reported separately by substance; light output and worker capacity keep their declared meaning. Missing physical models never generate invented impacts.
- A candidate with adequate declared inputs passes its enabled checks; an inadequate known input fails; absent required evidence yields unknown. An empty criterion set cannot produce a positive suitability claim.
- Known failed checks and unknown checks remain visible together. Every result names the criterion, values, units and evidence/assumption.
- Out-of-coverage regions remain inspectable and hypothetical placement remains possible with an explicit insufficient-data state.
- A power/water budget is counted once within its scope, including other scenario buildings. Editing/moving the same building does not count it twice.
- A test demand of 160 m³ against a declared 200 m³ allocation passes unstressed; a 0.5 water-availability multiplier yields 100 m³ supply and a 60 m³ shortfall. Reset restores the original result.
- Moving a building recomputes location-dependent checks and preserves its exact coordinates and definition snapshot after reload.
- Scenario branching preserves inputs/results reproducibly; editing stress controls in the branch cannot affect the original.
- Preview/cancel creates no project. Repeated clicks while saving do not create duplicate buildings. Switching scenarios cannot submit a preview to the wrong scenario.
- Bounded candidate search remains responsive; it never enumerates high-resolution cells for the whole Earth or issues one upstream request per cell.
- Baseline observations and raw/prepared data files are unchanged by building, editing, deleting or stress testing.

Use focused calculation and API persistence tests for the substantive new behaviours, existing H3 tests for the spatial contract, and frontend type/build checks. Run the backend tests that require PostgreSQL against a disposable test database, not against the user's saved scenarios. Manually verify the complete define → find → build → edit/move → stress → reload flow.
