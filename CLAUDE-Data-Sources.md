# CLAUDE.data-sources.md — Data integration catalogue

Last reviewed against public provider documentation: **2026-11-07**.  
Companions: [project overview](./CLAUDE.md), [mapping plan](./CLAUDE.mapping.md).

## Purpose and status

This is the intended data universe and integration backlog for New Worlds. It consolidates the sources discussed in planning and adds a few directly useful sources for water-risk and solar scenarios. It is not a claim that every source has been downloaded, licensed for this application, or integrated.

“Route” means the official API, catalogue, download, SDK or registration path. Proposed application routes are defined separately at the end. Public documentation was reviewed; authenticated requests, accounts, subscriptions and live data pipelines have not been tested or created.

Use product metadata and the licence attached to the actual release as the final authority. A free download, publicly viewable map, or open-source SDK is not itself permission to redistribute the underlying data.

### Priority

- **P0 — build first:** smallest useful set for the 24-hour demo.
- **P1 — add if ready:** a limited subset with an uncomplicated adapter.
- **P2 — later:** useful expansion requiring more processing or validation.
- **GATED — permissions/contract:** do not make the public demo depend on it until its conditions are resolved.

These are recommended priorities, not a request to integrate everything immediately.

### Evidence types

Use separate labels for satellite retrievals, in-situ measurements, reported records, modelled fields, and scenario assumptions. A material selector must also specify the quantity: occurrence, assay concentration, spectral signature, production, emissions, demand, or estimated stock.

## 1. Recommended first integrations

| Source ID | First useful layer | Why |
| --- | --- | --- |
| MAP-01 | Detailed basemap | Immediate global navigation |
| WATER-06 | WRI Aqueduct baseline water stress | Water-risk context; not available water volume |
| CTX-02 | NASA POWER solar irradiation and temperature | Simple inputs for explicitly assumed energy/cooling calculations |
| LAND-02 | WorldCover land-cover fractions | Context for where projects are placed |
| IND-01 | A selected GEM power/industrial asset release | Infrastructure context; not spare grid capacity |
| GEO-01 | One prepared EMIT mineral scene | Strong material-discovery demonstration if time allows |
| SOIL-01 | One SoilGrids variable | Easy-to-understand soil context using a predownloaded subset |

Only the first few are necessary. Freeze a dated demo snapshot and a prepared region; add other sources when the core interaction works. In particular, do not query one external service per visible hexagon.

Actual water allocations, electricity headroom, project material bills, and heat-network connections may be unavailable. Treat them as explicit scenario inputs rather than pretending that the above layers supply them.

## 2. Shared usage rules

Entries below refer to these policies to avoid repeating them.

| Policy | Operational meaning and reference |
| --- | --- |
| NASA | Check the collection licence first. NASA-led mission data without a restrictive notice default to CC0 under the NASA policy; third-party hosted data do not automatically inherit that status. Record the product DOI/version and acknowledge the source. [NASA science data licences](https://science.data.nasa.gov/about/license) |
| USGS | USGS-produced information is generally U.S. public domain; marked third-party material is excluded. Preserve provenance and credit the source. [USGS copyrights](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) |
| EPA | EPA-produced data default to U.S. public domain unless otherwise specified. Check contributor and dataset-specific metadata. [EPA data licence](https://pasteur.epa.gov/license/sciencehub-license.html) |
| SENTINEL | Sentinel data allow reuse, adaptation and distribution under their legal notice. Apply the prescribed source/year credit and indicate modification. Other CDSE-hosted data and website content can have different terms. [Sentinel legal notice](https://cds.climate.copernicus.eu/licences/ec-sentinel), [CDSE terms](https://dataspace.copernicus.eu/terms-and-conditions) |
| CC-BY-4 | Commercial reuse and redistribution are allowed with attribution, licence link and indication of modifications; do not add incompatible restrictions. [Licence](https://creativecommons.org/licenses/by/4.0/) |
| OGL | Use the Open Government Licence version attached to the dataset, with provider attribution. Preserve exclusions and third-party notices. [OGL v3](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) |
| PRODUCT-SPECIFIC | Public access exists, but the exact product licence must be captured before publishing/exporting it. This is an unresolved integration step, not a blanket ban. |
| CONTRACT | Purchase or institutional access does not imply public redistribution rights. Verify display, derivative products, caching, training, exports and downstream customer access under the actual agreement. |

Keep access cost separate from data rights. Open data may require registration and paid compute; commercial imagery may have separately negotiated derived-product rights.

## 3. Basemaps and access platforms

### MAP-01 — OpenFreeMap and OpenStreetMap — P0

- **Provides:** worldwide cartographic context: roads, settlements, waterways, buildings and other mapped features; completeness varies.
- **Route:** [OpenFreeMap quick start](https://openfreemap.org/quick_start/). MapLibre style: `https://tiles.openfreemap.org/styles/liberty`. Public instance does not require an API key.
- **Conditions:** [OpenFreeMap terms/attribution guidance](https://openfreemap.org/); underlying [OSM data licence](https://www.openstreetmap.org/copyright) is ODbL. Preserve attribution. Distributed derivative databases can trigger share-alike obligations; displaying a basemap does not automatically relicense unrelated application code.
- **Use:** render tiles as a background. For numerical OSM feature analysis, obtain a permitted data extract/API route separately; rendered tiles are not a complete analysis database. Public OSM tile/API services have separate usage policies.

### MAP-02 — MapTiler maps and satellite imagery — P1 / plan-dependent

- **Provides:** map tiles and a satellite/aerial imagery mosaic. Resolution and acquisition dates vary.
- **Route:** [API documentation](https://docs.maptiler.com/cloud/api/), [satellite description](https://docs.maptiler.com/schema-raster/satellite/). Create an account and use the selected map/tileset ID with a domain-restricted public API key.
- **Conditions:** [terms](https://www.maptiler.com/terms/) and the actual plan govern use, attribution, quotas and caching. The API documentation states that routing its API through a proxy requires a custom agreement. Confirm analysis/rehosting rights separately.
- **Use:** optional background selector. Do not promise an always-current satellite view or treat rendered imagery as permission to reconstruct the provider's dataset.

### ACCESS-01 — NASA Earthdata / CMR / earthaccess — shared access route

- **Provides:** discovery and access for NASA Earth-science collections, not one homogeneous dataset.
- **Route:** [Earthdata Search](https://search.earthdata.nasa.gov/), [CMR API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html), [earthaccess API](https://earthaccess.readthedocs.io/en/latest/api/). CMR base: `https://cmr.earthdata.nasa.gov/search/`; collection/granule JSON searches are documented there. Use `earthaccess.search_data` and `download`/`open` after choosing a collection/version.
- **Conditions:** NASA policy plus each collection's licence. Earthdata Login is required for many protected downloads. CMR discovery and data-file authorisation are separate.
- **Use:** search by region/date/product; download small numerical subsets. Record source filenames, DOI, version, scaling and QA flags. Do not query all granules without a collection filter.

### ACCESS-02 — Copernicus Data Space Ecosystem — shared access route

- **Provides:** Sentinel imagery and selected complementary/service datasets.
- **Route:** [API overview](https://documentation.dataspace.copernicus.eu/APIs.html), [STAC documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html). Current STAC root: `https://stac.dataspace.copernicus.eu/v1/`; `/collections` for discovery and `/search` for item queries. OData, S3, openEO and Sentinel Hub routes are also documented.
- **Conditions:** SENTINEL for Sentinel products; inspect other collection licences. Registration/tokens and usage quotas apply to relevant services. Processing quotas are separate from permission to use the data.
- **Use:** prefer ready-made products and bounded subsets. Avoid the legacy `catalogue.dataspace.copernicus.eu/stac` endpoint, documented as deprecated from November 2025.

### ACCESS-03 — Microsoft Planetary Computer — alternative access route

- **Provides:** a catalogue of hosted geospatial datasets, often with cloud-friendly assets.
- **Route:** [catalogue](https://planetarycomputer.microsoft.com/catalog), [catalogue documentation](https://planetarycomputer.microsoft.com/docs/concepts/data-catalog/), [SAS access documentation](https://planetarycomputer.microsoft.com/docs/concepts/sas/). Use STAC discovery and `planetary_computer.sign` for protected Azure asset URLs.
- **Conditions:** licences belong to individual datasets. Public discovery does not override source rights. SAS tokens expire; service rate limits apply.
- **Use:** convenient access to selected COGs and examples. Deduplicate against NASA/CDSE by upstream product and asset, not by hosting URL.

### ACCESS-04 — Google Earth Engine — optional processing route

- **Provides:** a large data catalogue and server-side geospatial processing.
- **Route:** [catalogue](https://developers.google.com/earth-engine/datasets/catalog), [commercial configuration guidance](https://developers.google.com/earth-engine/guides/transition_to_commercial). Requires a configured Cloud project and authorised account.
- **Conditions:** each dataset retains its licence; Earth Engine service eligibility, verification, billing and quotas are separate. Commercial use requires the appropriate paid configuration.
- **Use:** only if the team already has working access. Export a bounded result with provenance. Do not assume a hackathon account is approved or that service access grants commercial data rights.

## 4. Surface minerals, geology and raw resources

### GEO-01 — NASA EMIT — P1

- **Provides:** imaging spectroscopy, mineral identification/band-depth/uncertainty products, and aggregated spectral-abundance products. Core groups: calcite, chlorite, dolomite, goethite, gypsum, hematite, illite+muscovite, kaolinite, montmorillonite and vermiculite.
- **Route:** [mission](https://earth.jpl.nasa.gov/emit/), [official mineral tutorial](https://nasa.github.io/LPDAAC-Data-Resources/external/Working_with_EMIT_L2B_Mineralogy.html), ACCESS-01. Search EMIT mineral collections and pin the chosen version.
- **Conditions:** NASA policy and product citation. Detailed mineral identification is approximately 60 m, while aggregated products can be much coarser. Observations cover selected areas within the ISS latitude envelope, not complete global mineral coverage.
- **Use:** QA-mask, geolocate and aggregate valid pixels to H3. Spectral abundance/band depth is not automatically mass concentration or buried reserves. Additional mineral classes need validation.

### GEO-02 — EnMAP — P2 / redistribution restrictions

- **Provides:** hyperspectral imagery for surface-material, vegetation and water analysis; generally requires custom interpretation.
- **Route:** [data access](https://www.enmap.org/data_access/): registered EOWEB access, planning portal, and available analysis-ready geoservices.
- **Conditions:** [EnMAP licence](https://www.enmap.org/data/resources/EnMAP_Data_License.pdf) permits free commercial and non-commercial use, but limits raw-data transfer/public downloadable redistribution. It distinguishes irreversible value-added products from recoverable original pixels. Use required DLR/EnMAP credit and respect affiliated-user conditions.
- **Use:** keep raw assets out of public download routes unless explicitly permitted. Confirm the intended H3 output qualifies under the licence; a format conversion alone is not necessarily an irreversible derivative.

### GEO-03 — PRISMA — GATED

- **Provides:** hyperspectral imagery suitable for research and custom material mapping.
- **Route:** [mission and portal access](https://www.asi.it/en/earth-science/prisma/), [PRISMA portal](https://prisma.asi.it/).
- **Conditions:** the [2022 commercial policy](https://www.asi.it/en/2022/04/the-prisma-hyperspectral-mission-opens-up-to-commercial-exploitation-of-products/) supersedes the earlier blanket non-commercial description. Commercial derivative use has a qualifying group structure led by an Earth-observation organisation operating in Italy. Images remain free under that route; irreversible transformation and current registered-user terms matter. [Phase-2 policy record](https://trasparenza.asi.it/archivio28_provvedimenti-amministrativi_-1_176439_725_1.html).
- **Use:** later integration only after confirming the applicable access group and display/redistribution terms. Do not rely on a 2020 announcement as current policy.

### GEO-04 — ASTER archive — P2

- **Provides:** multispectral and thermal observations useful for geological indicators, surface temperature and historical analysis.
- **Route:** [NASA ASTER access](https://terra.nasa.gov/data/aster-data), Earthdata/USGS catalogue routes linked there.
- **Conditions:** no-cost archive access; inspect the selected product's licence and required citation rather than applying one licence to every ASTER-derived product.
- **Use:** select valid acquisition dates and available bands. Check instrument/band history, particularly SWIR availability, before building alteration indices. These are indicators requiring validation, not universal ore measurements.

### GEO-05 — USGS Spectral Library v7 — P2

- **Provides:** laboratory/field reference spectra for minerals, rocks, soils, vegetation, liquids, chemicals, coatings and manufactured materials.
- **Route:** [library and downloads](https://www.usgs.gov/labs/spectroscopy-lab/usgs-spectral-library), [data release](https://www.usgs.gov/data/usgs-spectral-library-version-7-data).
- **Conditions:** USGS policy; retain sample descriptions and release citation.
- **Use:** reference spectra for later detector development. This is not a geolocated world distribution dataset. A spectrum existing in the library does not establish that a satellite can detect the material under actual conditions.

### GEO-06 — USGS mineral occurrences, MRDS, USMIN and mineral statistics — P1/P2

- **Provides:** known deposits/occurrences, selected mine and district records, and domestic/international mineral production information.
- **Route:** [Mineral Resources Data](https://www.usgs.gov/programs/mineral-resources-program/mineral-resources-data), [MRDS](https://mrdata.usgs.gov/mrds/). Follow dataset download/service links and the data dictionaries.
- **Conditions:** USGS policy plus individual release metadata. MRDS is legacy information and does not reliably reflect current mine status, ownership, reserves or production.
- **Use:** point/polygon overlays with commodity and record date. Keep occurrences, reserves, resources and production separate. Country statistics remain country-level context; do not replicate their totals into every hexagon.

### GEO-07 — USGS geochemistry, Earth MRI and Critical Minerals in Ores — P2

- **Provides:** laboratory assays, regional geology/geophysics, and exploration survey products; availability varies by survey. CMiO contributes multielement deposit geochemistry.
- **Route:** [National Geochemical Database](https://www.usgs.gov/centers/gggsc/science/national-geochemical-database), [CMiO](https://pubs.usgs.gov/publication/fs20253002), [Earth MRI through mineral data catalogue](https://www.usgs.gov/programs/mineral-resources-program/mineral-resources-data).
- **Conditions:** USGS policy for USGS outputs; international compilations require their release metadata and contributor credits.
- **Use:** preserve sample medium, depth, assay units, detection limits and laboratory methods. Magnetic, gravity and radiometric fields are geological evidence, not direct universal concentrations.

### GEO-08 — British Geological Survey — P1 for a UK subset

- **Provides:** bedrock/superficial geology, hydrogeology, borehole records, soil parent material, geochemistry, gravity and magnetic surveys; product coverage and detail vary.
- **Route:** [open map downloads](https://www.bgs.ac.uk/geological-data/opengeoscience/map-data-downloads/), [NGDC access](https://www.bgs.ac.uk/ngdc/access-data/), [GeoIndex services](https://map.bgs.ac.uk/arcgis/rest/services/GeoIndex_Onshore).
- **Conditions:** datasets specifically listed on the open-download page use OGL with BGS/UKRI attribution. [Other BGS products can require paid licences](https://www.bgs.ac.uk/information-hub/licensing/). Public viewing of borehole scans does not imply every scan can be republished.
- **Use:** choose a named open product and record its map scale. Boreholes are observations at particular depths and locations; OCR interpretation is later work.

### GEO-09 — Geoscience Australia and Australian state surveys — P2

- **Provides:** mineral resources, geology, drilling, geochemistry, geophysics, exploration reports, terrain and groundwater information.
- **Route:** [GA critical-mineral geoscience](https://www.ga.gov.au/scientific-topics/minerals/critical-minerals/precompetitive-critical-mineral-geoscience), [Australian portal directory](https://www.australiaminerals.gov.au/portals), [NSW geoscience API](https://api.geoscience.nsw.gov.au/).
- **Conditions:** GA's [default CC BY 4.0 policy](https://www.ga.gov.au/copyright) excludes specified and third-party content. State portals and company-deposited reports have their own product conditions.
- **Use:** ingest specific documented releases and preserve original sample/asset IDs. Public exploration reports may include outdated interpretations or different resource classifications.

### Resource selector enabled by GEO-06–09

Catalogue these only where a source actually has relevant records:

| Family | Intended materials |
| --- | --- |
| Precious metals | Gold, silver, platinum, palladium and other platinum-group metals |
| Base metals | Copper, lead, zinc, tin |
| Battery materials | Lithium, cobalt, nickel, manganese, graphite, vanadium |
| Steel/alloy materials | Iron, chromium, molybdenum, tungsten, niobium |
| Rare earths | Neodymium, praseodymium, dysprosium, terbium, cerium, lanthanum and other reported elements |
| Other critical materials | Gallium, germanium, indium, antimony, bismuth, tantalum, tellurium |
| Light/specialist metals | Aluminium-bearing ores, magnesium, titanium, zirconium, beryllium |
| Industrial/fertiliser materials | Phosphate rock, potash, sulphur, limestone, silica, feldspar, fluorspar, barite, talc, kaolin, salt, borates |
| Construction materials | Sand, gravel, crushed rock, clay, dimension stone |
| Energy resources | Coal, uranium and reported oil/gas resources |

The menu is an extensible vocabulary, not a promise of measured global coverage for every item. Represent “no observations” explicitly.

## 5. General imagery and surface conditions

### OBS-01 — Copernicus Sentinel-1 — P2

- **Provides:** radar imagery for surface-water extent, flood mapping, change detection and, with specialised processing, surface deformation. Radar works through cloud and at night.
- **Route:** [mission collection](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-1), ACCESS-02. Select an appropriate product, orbit, acquisition mode and polarisation before processing.
- **Conditions:** SENTINEL; service processing/download quotas still apply.
- **Use:** derived flood or change layers. Backscatter is not a universal chemical-composition sensor. Deformation requires a suitable acquisition sequence and validated processing; a single image does not establish subsidence.

### OBS-02 — Copernicus Sentinel-2 — P1 for a prepared scene

- **Provides:** multispectral optical imagery with bands at 10, 20 and 60 m; vegetation, land-cover, exposed-surface and water-colour indicators.
- **Route:** [mission collection](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2), ACCESS-02. Prefer surface-reflectance products when suitable, and inspect cloud/quality masks.
- **Conditions:** SENTINEL. Preserve acquisition date, processing level and source credits in derived layers.
- **Use:** vegetation indices, change comparison and supporting context for mineral interpretation. Index values are not tonnes of vegetation, buried mineral stocks or laboratory water chemistry.

### OBS-03 — Copernicus Sentinel-3 — P2

- **Provides:** ocean/land colour, surface-temperature and other mission-specific products at coarser scales than Sentinel-2.
- **Route:** [mission collection](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-3), ACCESS-02. Select the instrument/product needed; use specialist ocean services for ready-made ocean products.
- **Conditions:** SENTINEL; retain product-specific calibration and quality information.
- **Use:** broad surface and coastal context. Match spatial and temporal support to the H3 summary, and do not treat finer display cells as new measurements.

### OBS-04 — USGS/NASA Landsat — P1 for historical comparison

- **Provides:** a long record of land imagery, surface reflectance and surface temperature; availability depends on mission and product.
- **Route:** [official access guide](https://www.usgs.gov/landsat-missions/landsat-data-access), [EarthExplorer](https://earthexplorer.usgs.gov/), [M2M API](https://m2m.cr.usgs.gov/), or documented Collection 2 cloud/STAC access. Account-based downloads and public cloud assets have different access mechanics.
- **Conditions:** USGS policy; operational Landsat products are available at no data-purchase cost. Record the collection, product ID and processing version.
- **Use:** compare land, water and thermal conditions across dates. Apply scale factors, cloud masks and sensor-specific QA; distinguish surface temperature from air temperature.

### OBS-05 — NASA ECOSTRESS — P2

- **Provides:** thermal surface observations and products such as land-surface temperature, evapotranspiration and plant-water-stress indicators. Detailed products are approximately 70 m, with product-dependent processing and coverage.
- **Route:** [ECOSTRESS data](https://ecostress.jpl.nasa.gov/data), ACCESS-01. Select the numerical product and version; evapotranspiration is a derived model product.
- **Conditions:** NASA policy plus the selected collection citation. ISS sampling is intermittent and is not complete coverage of all latitudes or times.
- **Use:** heat and vegetation-water context. A snapshot does not measure available cooling-water allocation or a project's annual water demand.

### OBS-06 — NASA MODIS and VIIRS products — P2

- **Provides:** broad repeat observations and derived products for vegetation, aerosols, temperature, snow, clouds and other Earth-system variables; product resolution and record length vary.
- **Route:** [LAADS tools](https://ladsweb.modaps.eosdis.nasa.gov/tools-and-services/), [API v2 specification](https://ladsweb.modaps.eosdis.nasa.gov/tools-and-services/api-v2/specs/), ACCESS-01. Use the relevant DAAC for the chosen collection, not LAADS for every MODIS/VIIRS product.
- **Conditions:** NASA policy and collection metadata; scripted LAADS downloads require an accepted download token. Tokens for one service may not work on another.
- **Use:** historical or seasonal context after QA. Use LAND-05 for ready-made active-fire observations instead of rebuilding that pipeline.

## 6. Atmosphere, emissions and pollutants

### AIR-01 — Sentinel-5P / TROPOMI — P1 for one prepared gas layer

- **Provides:** atmospheric products for nitrogen dioxide, sulphur dioxide, carbon monoxide, formaldehyde, ozone, methane and aerosol indicators, depending on the product.
- **Route:** [product overview](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel5P.html), [Sentinel Hub product documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S5PL2.html), ACCESS-02.
- **Conditions:** SENTINEL; apply the product's QA thresholds, units and recommended screening.
- **Use:** regional atmospheric context and changes. Many quantities are vertical columns or column-averaged mixing ratios, not ground-level concentrations. Do not label a column map as local breathing exposure or a facility's measured emissions.

### AIR-02 — Copernicus Atmosphere Monitoring Service — P2

- **Provides:** forecasts and reanalyses of atmospheric composition, including gases, particulate matter and aerosol components such as dust, sea salt, sulphate and carbonaceous aerosols, depending on product.
- **Route:** [CAMS data](https://atmosphere.copernicus.eu/data), [Atmosphere Data Store](https://ads.atmosphere.copernicus.eu/), [API setup](https://ads.atmosphere.copernicus.eu/how-to-api). Select a dataset in the catalogue and use its generated request example.
- **Conditions:** accept the selected dataset's licence and service terms. Standard CAMS/C3S data licences changed to CC BY 4.0 in July 2025; retain the actual release's metadata rather than applying an old licence universally. [Change notice](https://forum.ecmwf.int/t/cc-by-licence-to-replace-licence-to-use-copernicus-products-on-02-july-2025/13464).
- **Use:** label as modelled/assimilated fields. These products supply background conditions, not a validated local plume model for a new project.

### AIR-03 — IASI / AERIS trace-gas products — P2 / product-specific

- **Provides:** research products for gases such as ammonia, carbon monoxide, ozone, methane, nitrous oxide, formic acid and sulphur dioxide, plus other product-specific variables.
- **Route:** [IASI portal](https://iasi.aeris-data.fr/), [ammonia data](https://iasi.aeris-data.fr/nh3/). Follow each product page to its downloads/scripts; preserve the Level-2/Level-3 distinction.
- **Conditions:** [data-use policy](https://iasi.aeris-data.fr/data-use-policy/) requests investigator notification, appropriate citations and AERIS/provider acknowledgement; substantial use has additional collaboration expectations. Public commercial redistribution is not clearly granted by that page, so resolve it for the selected product before publishing.
- **Use:** additional atmospheric research layers. Preserve uncertainty, column definitions, vertical sensitivity and sampling; do not infer local fertiliser stocks from atmospheric ammonia.

### AIR-04 — Carbon Mapper — GATED

- **Provides:** methane and carbon-dioxide plume detections and emission estimates for observed sources, with observation metadata. Coverage is selective.
- **Route:** [data portal and access](https://carbonmapper.org/data), [product guide](https://carbonmapper.org/articles/product-guide), [API documentation](https://api.carbonmapper.org/api/v1/docs). Register and follow the current portal/API authorisation flow.
- **Conditions:** [terms](https://carbonmapper.org/terms) restrict ordinary access to specified non-commercial emissions-related purposes and impose attribution/downstream conditions. A paid aggregator or unrelated commercial commodity-analysis feature needs a separate agreement. Do not interpret public API access as an unrestricted open-data licence.
- **Use:** emissions discovery only within the permitted purpose. Keep this source disabled for commercial deployment until appropriate rights are established. An undetected or unobserved plume is not proof of zero emissions.

## 7. Soil, water quantity and water quality

### SOIL-01 — ISRIC SoilGrids — P1

- **Provides:** modelled soil properties at approximately 250 m and standard depth intervals: organic carbon, nitrogen, pH, texture fractions, bulk density, coarse fragments and cation-exchange capacity, with uncertainty products.
- **Route:** [SoilGrids](https://isric.org/explore/soilgrids), [access documentation](https://docs.isric.org/globaldata/soilgrids/), [WCS](https://docs.isric.org/globaldata/soilgrids/wcs.html). Use bounded WCS requests or documented file downloads. WMS is for visual maps.
- **Conditions:** CC-BY-4, with ISRIC/product acknowledgement. The [current FAQ](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_02.html) reports the REST service as paused; do not make it the demo's required live endpoint.
- **Use:** preload one property and depth for a region. Honour scale factors and uncertainty. Soil mineral or nitrogen content is not automatically recoverable fertiliser inventory.

### WATER-01 — NASA SMAP — P2

- **Provides:** surface-soil-moisture retrievals and associated products; selected model-assimilated products also estimate root-zone conditions.
- **Route:** [SMAP mission](https://smap.jpl.nasa.gov/), ACCESS-01. Select the exact level, native grid and version in Earthdata.
- **Conditions:** NASA policy plus the chosen collection's licence/citation. Do not mix retrieval and model products without identifying them.
- **Use:** agricultural dryness and soil-water context. Soil moisture is not river discharge, groundwater pumping rights or available industrial water. Coarse products retain their original resolution even when displayed on smaller hexagons.

### WATER-02 — GRACE / GRACE-FO and derived water-storage products — P2

- **Provides:** broad regional changes in terrestrial water storage; groundwater and soil-moisture estimates require additional modelling or separation of water components.
- **Route:** ACCESS-01 and [NASA GRACE data-assimilation products](https://earth.gsfc.nasa.gov/hydro/data/groundwater-and-soil-moisture-conditions-grace-data-assimilation).
- **Conditions:** NASA policy and each derived product's citation/version. Record the reference period and anomaly definition.
- **Use:** regional groundwater/storage trends, with appropriate uncertainty. These observations do not support independent kilometre-scale aquifer estimates or the depth/yield of a particular well.

### WATER-03 — SWOT surface-water observations — P2

- **Provides:** water-surface elevation and extent products for observed inland/coastal waters, depending on collection.
- **Route:** ACCESS-01; example [100 m raster water product](https://data.nasa.gov/dataset/swot-level-2-water-mask-raster-image-100m-data-product-version-c). Use the selected collection's documentation to discover current files and versions.
- **Conditions:** NASA/product-specific policy and mission credits; retain geolocation and quality flags.
- **Use:** surface-water context and temporal change. Surface height/extent alone does not provide water chemistry, legal allocations or a complete volumetric stock without further geometry and modelling.

### WATER-04 — US Water Quality Portal — P2

- **Provides:** monitoring-station samples and results from USGS, EPA and other contributors: nutrients, metals, physical properties, organic contaminants and biological measurements where sampled.
- **Route:** [portal](https://waterqualitydata.us/), [beta/current-format portal](https://waterqualitydata.us/beta/), [web services](https://www.waterqualitydata.us/webservices_documentation/), [user guide](https://waterqualitydata.us/portal_userguide/). Obtain the current WQX-format request from the relevant interface/documentation.
- **Conditions:** USGS/EPA policies for their outputs; retain original contributors and release terms. The legacy WQX 2.2 service does not include newer USGS observations after 11 March 2024. Do not silently use it as a current-data feed.
- **Use:** preserve sampling date, medium, depth, method, detection limit and result qualifier. A non-detect is not zero; one sample is not an entire hexagon's water quality. Only expose PFAS, pesticides or other analytes when actual records exist.

### WATER-05 — Environment Agency Water Quality Explorer, England — P1 for a UK sample

- **Provides:** water-sample results from English monitoring locations, including chemical and physical parameters; analyte coverage varies.
- **Route:** [official dataset listing](https://www.data.gov.uk/dataset/583e771f-1af6-4934-b8f0-28f1d1ddd48c/water-quality-explorer), [API directory](https://www.api.gov.uk/ea/water-quality/), [water-quality access](https://environment.data.gov.uk/water-quality/view/landing). Follow the current explorer/download links and confirm the chosen API version.
- **Conditions:** the current dataset listing specifies OGL. Credit the Environment Agency and preserve sampling/method metadata; other EA datasets can have different licences.
- **Use:** observations at sample points, not a complete national concentration surface. Transform British National Grid coordinates when supplied; never interpret metres as longitude/latitude.

### WATER-06 — WRI Aqueduct — P0 for risk context

- **Provides:** basin-level baseline water-risk indicators and selected future scenarios, including water stress; no universal extraction budget.
- **Route:** [Aqueduct 4.0 release](https://www.wri.org/data/aqueduct-global-maps-40-data), [downloads](https://www.wri.org/aqueduct/data), [FAQ](https://www.wri.org/aqueduct/faq). Download a versioned basin dataset and spatially join it to project locations/H3 cells.
- **Conditions:** CC-BY-4 with WRI/Aqueduct attribution and the release citation; retain scenario/year and indicator definitions. Follow any registration/usage reporting requested by the download workflow.
- **Use:** water-risk shading and scenario context. Do not divide a stress index among hexagons or subtract project consumption from it as though it were cubic metres. Large cells crossing basins need a documented aggregation rule.

## 8. Oceans, coasts and marine resources

### OCEAN-01 — NASA PACE / Ocean Biology DAAC — P2

- **Provides:** ocean-colour observations and derived products such as chlorophyll and selected phytoplankton-related indicators, plus other mission-specific atmospheric/ocean variables.
- **Route:** [OceanColor data access](https://oceandata.sci.gsfc.nasa.gov/), [PACE data introduction](https://www.nasa.gov/earth/nasas-pace-data-on-ocean-atmosphere-climate-now-available/), ACCESS-01. Select the instrument, processing level and product before downloading.
- **Conditions:** NASA policy and product citation; use appropriate ocean/cloud/quality masks.
- **Use:** marine ecosystem exploration and change. Chlorophyll or spectral community estimates do not directly measure fish stocks, catch potential or harvestable biomass.

### OCEAN-02 — Copernicus Marine Service — P2

- **Provides:** physical and biogeochemical ocean products. Depending on dataset: currents, temperature, salinity, oxygen, nutrients, chlorophyll, plankton, productivity, pH, carbon variables and sea ice. Distinguish satellite, in-situ and model products.
- **Route:** [catalogue example](https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_BGC_001_028/description), [Toolbox guide](https://help.marine.copernicus.eu/en/articles/7949409-copernicus-marine-toolbox-introduction). Use `copernicusmarine` with a catalogue dataset ID and bounded space/time/depth; follow [account guidance](https://help.marine.copernicus.eu/en/articles/4220332-how-to-register-for-copernicus-marine-service).
- **Conditions:** service access is free, including commercial purposes, under its applicable licence and [citation/derivative-credit requirements](https://help.marine.copernicus.eu/en/articles/4444611-citing-copernicus-marine-products-and-services). Preserve each product DOI and any additional notices.
- **Use:** map the selected depth and time, not an unspecified ocean-wide average. Dissolved iron or nutrients are ecosystem variables, not an economically recoverable mineral reserve.

### OCEAN-03 — EMODnet — P2

- **Provides:** European marine bathymetry, geology, seabed substrate, habitats, chemistry, physics, biology and human-activity datasets, varying by theme and region.
- **Route:** [theme catalogue](https://emodnet.ec.europa.eu/en/emodnet-themes), [geology](https://emodnet.ec.europa.eu/en/geology), [web-service documentation](https://github.com/EMODnet/Web-Service-Documentation). Use theme-specific WMS/WFS, downloads or numerical services; WMS screenshots are not analytical data.
- **Conditions:** [EMODnet terms](https://emodnet.ec.europa.eu/en/terms-use-emodnet-online-services-data-and-data-products). EMODnet-produced products generally use CC-BY-4 unless stated otherwise; original contributed datasets can retain different conditions. Capture the actual provider and licence.
- **Use:** coastal/seabed context and recorded mineral occurrences. Do not infer commercially extractable resources, seabed ownership or permission to operate from geology alone.

## 9. Land cover, agriculture, forests and fire

### LAND-01 — Copernicus Land Monitoring Service — P2

- **Provides:** land-cover, vegetation, biophysical and other land-monitoring products, including selected productivity, snow, water, soil-moisture and ground-motion layers. Coverage/resolution depend on product.
- **Route:** [product catalogue](https://land.copernicus.eu/en/products), [CDSE access documentation](https://documentation.dataspace.copernicus.eu/Data/CopernicusServices/CLMS.html). Use documented download/STAC/OData/S3 routes for the chosen collection; availability differs across products.
- **Conditions:** [CLMS data policy](https://land.copernicus.eu/en/data-policy) allows broad reuse, including commercial use, subject to acknowledgement and applicable notices. Preserve product source, version and modification information.
- **Use:** ready-made land indicators before developing new image classifiers. Check units and temporal composites; productivity indicators are not necessarily harvestable crop yield.

### LAND-02 — ESA WorldCover — P0/P1

- **Provides:** global 10 m land-cover classifications for specific release years, including tree cover, cropland, built-up, water and other classes.
- **Route:** [data access](https://esa-worldcover.org/en/data-access): downloadable tiles, cloud access and visual map services. Choose the 2020 or 2021 release deliberately and record its version.
- **Conditions:** CC-BY-4 with the prescribed product citation and modifications noted.
- **Use:** calculate class-area fractions within cells using the source pixel grid. This supports site context; it does not establish legal land use, ownership, current land availability or permission to build. A newer application date does not make the source imagery current.

### LAND-03 — ESA WorldCereal — P2

- **Provides:** global-scale seasonal/annual crop and irrigation classifications with confidence layers for specified products and years; the 2021 suite includes temporary crops, maize and selected cereals.
- **Route:** [global maps and area downloads](https://esa-worldcereal.org/en/products/global-maps), [2021 release](https://zenodo.org/records/7875105), or the linked Earth Engine collection.
- **Conditions:** the 2021 product is distributed as CC-BY-4, also documented by [Digital Earth Africa's product guide](https://docs.digitalearthafrica.org/en/latest/data_specs/ESA_World_Cereal_specs.html); preserve the release DOI and credits. Recheck the metadata for other releases and contributed reference datasets, which can carry different licences.
- **Use:** crop/irrigation context with season and agro-ecological zone. Crop presence does not provide current yield, fertiliser demand, ownership or available irrigation supply. Some zones/products have missing coverage.

### LAND-04 — NASA GEDI — P2

- **Provides:** lidar observations and derived canopy-height/structure and above-ground biomass products, including footprint-level and gridded products.
- **Route:** [NASA GEDI resources](https://github.com/nasa/GEDI-Data-Resources), [ORNL product guide](https://github.com/ornldaac/gedi_tutorials/blob/main/docs/datasets.md), ACCESS-01.
- **Conditions:** NASA policy plus the selected product's licence and citation. Match the processing level, quality filters and uncertainty fields.
- **Use:** forest structure and biomass context. Footprints sample limited tracks within the ISS latitude range; they are not complete measurements of every forest pixel. Biomass does not imply harvest rights or immediately available timber.

### LAND-05 — NASA FIRMS — P1

- **Provides:** active-fire/thermal-anomaly detections and related attributes such as fire radiative power, acquisition time and confidence.
- **Route:** [Area API documentation](https://firms.modaps.eosdis.nasa.gov/api/area). Obtain a free MAP_KEY and use the documented CSV area route with source, bounding box and day range. Historical standard-quality and near-real-time products serve different purposes.
- **Conditions:** NASA/source-product policy and required acknowledgements; respect the current transaction limits and permitted request windows.
- **Use:** recent-fire context and scenario stress events. A hotspot is not always a wildfire, a fire perimeter, a burned-area estimate or a chemical concentration; retain confidence and source flags.

## 10. Weather, energy potential, terrain and population

### CTX-01 — ERA5 / ERA5-Land — P2

- **Provides:** modelled/assimilated weather and climate fields such as temperature, precipitation, wind and surface energy/water variables, depending on dataset.
- **Route:** [Climate Data Store](https://cds.climate.copernicus.eu/), [API setup](https://cds.climate.copernicus.eu/how-to-api). Register, accept the dataset licence and use the request generated by its download form.
- **Conditions:** current standard C3S licensing uses CC-BY-4 following the 2025 change described under AIR-02. Preserve the licence attached to the chosen product and comply with CDS service terms.
- **Use:** dated conditions and seasonal baselines. Retain native grid/time resolution and accumulation conventions. Wind speed alone does not establish turbine output without height and turbine assumptions.

### CTX-02 — NASA POWER — P0/P1

- **Provides:** satellite/model-derived solar and meteorological parameters useful for renewable-energy and environmental context, with product-dependent spatial/temporal support.
- **Route:** [API tutorial](https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/), [daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/). Choose the correct community and temporal endpoint; point queries use longitude, latitude, parameter names, start/end dates and format.
- **Conditions:** retain NASA POWER and underlying source/product acknowledgements; check the selected product's rights and API limits. Open access does not mean unlimited requests.
- **Use:** prefetch/cross-cell cache native-grid values. Solar irradiation can feed an explicitly assumed panel area/efficiency calculation. Read returned units and time standard; do not confuse irradiation with installed capacity or continuous electrical output.

### CTX-03 — Copernicus DEM — P1/P2

- **Provides:** elevation surface models, including globally available GLO-30 and GLO-90 products. Surface elevation can include vegetation/buildings; it is not always bare-earth terrain.
- **Route:** [collection and access](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM), ACCESS-02. Select the correct release and tile assets.
- **Conditions:** the [Copernicus DEM licences](https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf) distinguish freely licensed GLO products from restricted products such as EEA-10. Follow the DEM-specific credits and downstream conditions; this is not automatically the Sentinel licence.
- **Use:** elevation/slope context and later hydrological preprocessing. Check acquisition/void-filling provenance. Coarse terrain does not support an engineering-grade site or flood-risk assessment.

### CTX-04 — WorldPop — P2

- **Provides:** modelled gridded population counts and related demographic datasets for specified countries/years/releases.
- **Route:** [data hub](https://hub.worldpop.org/), [FAQ](https://www.worldpop.org/faq/). Select a product and download its numerical raster plus metadata; no unverified API route is required for the first adapter.
- **Conditions:** population products generally use CC-BY-4 with attribution. Check each release: supporting covariates derived from third-party databases can have different terms, including ODbL.
- **Use:** estimate population associated with a cell or scenario area using appropriate count aggregation. Label model year and uncertainty; do not describe modelled residents as a live census or directly affected people without an exposure model.

### CTX-05 — Global Human Settlement Layer — P2

- **Provides:** built-up surface, settlement classifications and gridded population-related products for defined epochs/releases.
- **Route:** [GHSL download and conditions FAQ](https://human-settlement.emergency.copernicus.eu/faq.php); follow its dataset pages/JRC catalogue for numerical downloads. Public downloads do not require registration.
- **Conditions:** CC-BY-4 and European Commission reuse conditions. Cite both the relevant release/methodology publication and product-specific reference; a generic website credit is insufficient under its guidance.
- **Use:** urban context and settlement change. Select either GHSL or WorldPop for a given population metric, or make alternatives explicit; never sum overlapping estimates as separate populations.

## 11. Infrastructure, production, trade and activity

### IND-01 — Global Energy Monitor — P0/P1 for a selected tracker

- **Provides:** tracker-dependent records of power plants, mines and industrial/energy infrastructure, including location, status, capacity and ownership where reported. Includes selected steel, cement, oil/gas and other sectors.
- **Route:** [tracker directory](https://globalenergymonitor.org/node/12), [downloads](https://globalenergymonitor.org/download-data). Choose a named release and retain its methodology, thresholds and field definitions.
- **Conditions:** [GEM's default licence](https://globalenergymonitor.org/creative-commons-license) is CC-BY-4, but third-party inputs can differ. For example, [TransitionZero Solar Asset Mapper terms](https://www.transitionzero.org/terms/tz-sam-terms-of-use) include non-commercial restrictions. Preserve source-level exceptions rather than assuming every row shares GEM's default.
- **Use:** infrastructure and resource-production context. Nameplate capacity is not current generation or available grid capacity; a reported/proposed facility may not be operational.

### IND-02 — US EPA Toxics Release Inventory — P1/P2

- **Provides:** annual facility-reported releases, waste management and transfers of listed chemicals, subject to programme coverage/reporting thresholds.
- **Route:** [TRI basic data files](https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-present), [Envirofacts downloads](https://www.epa.gov/enviro/data-downloads), [EPA data platform](https://data.epa.gov/). Begin with a release-year bulk file.
- **Conditions:** EPA policy; preserve reporting year, original facility/chemical IDs and revision status. Review any dataset-specific notices.
- **Use:** reported emissions/material-flow context. Releases and transfers can refer to different media and destinations; avoid double counting. Annual reported mass is not ambient concentration, an instantaneous emission rate or proof of compliance/non-compliance.

### IND-03 — Environment Agency Pollution Inventory — GATED

- **Provides:** annual reported releases and transfers from regulated industrial activities in England, with chemical and facility records.
- **Route:** [official dataset listing and downloads](https://www.data.gov.uk/dataset/cfd94301-a2f2-48a2-9915-e477ca6d8b7e/pollution-inventory); select the relevant annual release.
- **Conditions:** the reviewed listing specifies the [EA Conditional Licence](https://www.gov.uk/government/publications/environment-agency-conditional-licence/environment-agency-conditional-licence), not a blanket OGL grant. Its permitted-use duration, onward-sharing conditions and third-party restrictions require checking for this application.
- **Use:** retain the source as a planned integration until public display/export rights are resolved. Do not inherit the open licence of WATER-05 merely because both datasets come from the Environment Agency.

### IND-04 — UK North Sea Transition Authority — P2

- **Provides:** selected UK offshore wells, fields, licences, infrastructure and production-related records; specialist subsurface data are available through other NSTA/NDR routes.
- **Route:** [access guide](https://www.nstauthority.co.uk/data-and-insights/about-nsta-data/how-to-access-our-data/), [open-data catalogue](https://open-data-ukcs-transition.hub.arcgis.com/search). Open a dataset's API resources to obtain its actual ArcGIS/GeoJSON/WMS route. [Example OGL wells dataset](https://www.data.gov.uk/dataset/37538d3f-c320-4153-ad72-3768a2f6be12/oga-wells-wgs84).
- **Conditions:** retain the selected dataset's licence; the example wells release uses OGL. UK National Data Repository well/seismic downloads can require registration and separate access permissions. Do not generalise one open release to all NDR assets.
- **Use:** energy infrastructure/resource context with date/status. Licensed acreage, a well or a mapped field does not establish commercially recoverable reserves or ownership of the data underneath it.

### IND-05 — UN Comtrade — GATED for public redistribution

- **Provides:** reported international merchandise-trade flows by reporter, partner, period and commodity classification, with value/quantity fields where available.
- **Route:** [Comtrade Plus](https://comtradeplus.un.org/), [developer portal](https://comtradedeveloper.un.org/), [data guide](https://uncomtrade.org/docs/data/), [bulk access](https://uncomtrade.org/docs/bulk-files/). Use the authorised API/download plan and documented query parameters.
- **Conditions:** [data-use policy](https://uncomtrade.org/docs/policy-on-comtrade-data-use/) limits redistribution except specified exemptions/permission; free access does not grant unrestricted public republishing. Observe plan limits and attribution; do not scrape the UI to bypass them.
- **Use:** country-level material-trade context. It does not identify actual supply contracts, mine-to-factory routes or local inventory. Keep outputs appropriately aggregated and rights-cleared before exposing them publicly.

### IND-06 — Global Fishing Watch — GATED for commercial use

- **Provides:** vessel activity and apparent-fishing-effort datasets and APIs for the vessels/time periods covered by its methods.
- **Route:** [fishing activity data](https://globalfishingwatch.org/dataset-and-code-fishing-activity/), [API documentation](https://api-doc.globalfishingwatch.org/). Register for the relevant token/access route.
- **Conditions:** [API licence and limits](https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits) specify CC BY-NC 4.0 for covered data/services, with attribution and rate limits. Obtain different rights before commercial use; check each requested product.
- **Use:** marine-activity context. Apparent fishing is inferred behaviour, not confirmed catch, fish biomass or a complete inventory of ships/cargo.

### IND-07 — NESO Carbon Intensity API, Great Britain — P1

- **Provides:** national and regional electricity carbon-intensity estimates/forecasts and generation-mix information for Great Britain.
- **Route:** [official API and terms](https://api.carbonintensity.org.uk/). Documented examples include `GET /intensity`, `GET /generation` and `GET /regional` on `https://api.carbonintensity.org.uk`.
- **Conditions:** CC-BY-4 and the linked API terms; preserve NESO attribution, timestamps and forecast/actual distinctions. Cache results and respect service availability.
- **Use:** a regional emissions-factor option for a UK demo. Match factor units and time to electricity consumption. Average regional intensity does not establish marginal emissions, contractual renewable supply or spare connection capacity.

## 12. River connectivity

### NET-01 — HydroSHEDS / HydroRIVERS / HydroBASINS — P1 for a prepared watershed

- **Provides:** drainage-related datasets, river reaches and basin identifiers. HydroRIVERS includes network relationships and estimates of long-term average discharge alongside geometric attributes.
- **Route:** [HydroRIVERS](https://www.hydrosheds.org/products/hydrorivers), [HydroBASINS](https://www.hydrosheds.org/products/hydrobasins), [technical documentation](https://data.hydrosheds.org/file/technical-documentation/HydroSHEDS_TechDoc_v1_4.pdf). Download a regional subset and preserve river/basin IDs to construct directed connections.
- **Conditions:** licences differ across the HydroSHEDS family; follow the [product-specific guidance](https://www.hydrosheds.org/faq). HydroRIVERS allows scientific, educational and commercial use under the referenced HydroSHEDS agreement, including its attribution and redistribution conditions.
- **Use:** trace upstream/downstream relationships rather than spreading water effects uniformly to adjacent cells. Long-term mean discharge is not today's flow or available abstraction. A calibrated water-allocation/transport model is still required for quantitative effects.

## 13. Commercial imagery expansion

### COM-01 — Planet — GATED / contract

- **Provides:** commercial imagery products from constellations such as PlanetScope, SkySat, Pelican and hyperspectral Tanager, subject to product availability and account entitlement.
- **Route:** [data documentation](https://docs.planet.com/data/), [Data API items](https://docs.planet.com/develop/apis/data/items/), and the account's documented ordering/tasking routes. Catalogue discovery, asset activation and download rights are distinct steps.
- **Conditions:** [licensing documents](https://www.planet.com/licensing-information/) and the signed order govern analysis, display, redistribution, derivatives, training and permitted users. Research/sample access is not automatically permission for an unrestricted public application.
- **Use:** later higher-detail or hyperspectral studies. Do not quote an assumed universal price or promise an unlicensed archive. Store contract-specific rights beside each asset and derived layer.

### COM-02 — Pixxel — GATED / contract

- **Provides:** commercial hyperspectral imagery and related archive/tasking services. Match the actual operating sensor's wavelength range and availability to the proposed analysis.
- **Route:** [constellation documentation](https://docs.pixxel.space/documentation/satellite-and-imagery/constellation-overview), [tasking/access guidance](https://docs.pixxel.space/documentation/getting-started/pricing-and-refunds/imagery-pricing/tasking), [Aurora platform](https://www.pixxel.space/). Use the account's current catalogue and API documentation.
- **Conditions:** [Aurora EULA](https://www.pixxel.space/aurora-end-user-license-agreement) and the actual imagery order govern use and downstream rights. Evaluate the purchased entitlement rather than assuming raw-data redistribution is permitted.
- **Use:** later material-classification experiments. Do not claim a planned future sensor is currently available, or that VNIR-only observations provide all SWIR mineral diagnostics.

## 14. What the platform can say about substances

Use the source's actual measurement meaning in the selector and legend. Do not collapse these into one generic “amount of material” field.

| Layer family | Appropriate source routes | Meaning we can support |
| --- | --- | --- |
| Exposed minerals | GEO-01–05, OBS-02/04 | Retrieved surface signature, classification or validated abundance proxy |
| Metals and ores | GEO-06–09 | Reported occurrences, assays, resources or production, with the source's classification |
| Soil carbon/nutrients/texture | SOIL-01 and sampling datasets | Modelled property at a stated depth, or a point sample |
| Atmospheric gases/aerosols | AIR-01–04 | Column, modelled concentration, index or plume estimate, as specified |
| Water contaminants | WATER-04/05 | Sampled concentration/result with method and detection qualifiers |
| Ocean nutrients/carbon/oxygen | OCEAN-01/02 | Retrieved or modelled water-column/surface variable at a stated depth |
| Vegetation/crops/biomass | OBS-02/06, LAND-01–04 | Cover, index, structural measure or modelled biomass; not automatic yield |
| Industrial chemical releases | IND-02/03 | Reported mass released/transferred over the reporting period |
| Commodity production/trade | GEO-06, IND-01/04/05 | Reported facility/country activity; not a universal local stock |
| Plastics, coatings and manufactured surfaces | GEO-05 plus suitable imagery and validation | Experimental classification only; no ready-made global concentration map is promised |

Subsurface stocks, rare trace compounds, PFAS, pesticides, pathogens and microplastics cannot be added as credible global satellite heatmaps simply by choosing their names. For these, use a suitable measured/validated dataset where it exists, retain its actual coverage, or label a new inference as experimental.

## 15. Inputs still required for quantitative project effects

The catalogue supplies observations and context. The simulation also needs the following inputs, which are not supplied universally by these sources:

| Required input | Intended acquisition/model route | Interim behaviour |
| --- | --- | --- |
| Usable water budget and abstraction/discharge limits | Named utility, regulator, catchment or site records with applicable rights | Show added demand and risk context; accept an explicit hypothetical budget |
| Electricity connection capacity and network constraints | Network operator/site data and a defined network model | Show demand and assumed supply; do not infer headroom from nearby plants |
| Project bill of materials | Manufacturer design, engineering inventory or licensed life-cycle dataset | User-supplied quantities; one-time construction inputs |
| PUE, WUE and cooling behaviour | Cited technology/site documentation or user assumptions | Expose coefficients and units; do not invent source-backed defaults |
| Heat-network viability | Declared connection, recoverable temperature/energy, losses and recipient demand | Transparent simplified link; cap useful heat by demand |
| Hourly renewable matching/storage | Time-series weather, technology performance and storage model | Report period energy balance; no claim of continuous renewable supply |
| Environmental transport | Hydrological, dispersion or ecological model calibrated to the question | Clearly illustrative scenarios; proximity alone is insufficient |
| Capital/operating cost and commodity prices | A named dated source with redistribution rights or entered assumptions | Omit financial forecasts until the inputs are documented |
| Land ownership, protected status and permission to build | Jurisdiction-specific cadastral, conservation and planning sources | No “buildable/approved” assertion from land cover alone |

These are future source-selection tasks, not hidden integrations. Do not fabricate a provider, endpoint, licence or numerical coefficient to fill the gap. A user-uploaded dataset is an additional route: require coordinate system, units, date, provenance and the user's declared rights, then apply the same validation as external adapters.

## 16. Access and processing rules

### Credentials, costs and requests

- Keep secret credentials, download tokens and signed asset URLs out of source control, logs and scenario exports. Use environment variables or server-side secret storage.
- Public browser map keys are an exception only when the provider explicitly designs them for that use. Restrict domains and scope, and follow the provider's proxy rules.
- Do not proxy every service by default: some providers prohibit it or require an agreement. Separate public basemap delivery from backend analytical downloads.
- Create accounts only when needed for selected integrations. Registration, subscriptions and provider correspondence are not prerequisites for writing these specifications.
- Rate-limit by provider, use bounded requests, handle 429/temporary errors with documented retry behaviour, and cache permitted results by product/version/region/time.
- Never download a whole global high-resolution archive merely to populate the visible map. Subset tiles, windows, dates and variables before processing.
- Freeze a small, licence-compatible demo snapshot. Store its retrieval date; do not describe cached values as live.

### Numerical ingestion

1. Choose the exact collection/version and capture the licence, metadata and citation.
2. Discover assets through the documented catalogue, API or download page.
3. Retrieve a bounded numerical subset. COG/GeoTIFF, NetCDF, Zarr, CSV, GeoJSON or source-specific formats are useful; a rendered map is not a substitute.
4. Decode CRS, units, scale/offset, no-data values, time/depth and quality flags.
5. Apply source-recommended quality screening before aggregation.
6. Preserve native records and their geometry separately from H3 summaries.
7. Aggregate using the variable's meaning: sums for additive counts, area-weighted statistics for suitable fields, categorical fractions for land cover, and original support geometry for basin/regional indices.
8. Write provenance and coverage beside each result; retain uncertainty and measurement qualifiers.
9. Expose only the display/export forms permitted for that asset or derivative.

Do not average concentrations from samples with different media/depths or merge incompatible time periods. A location repeated in multiple data hosts is not an independent observation. Use upstream product/granule/sample IDs for deduplication.

## 17. Source metadata contract

Implement the following source registry alongside the `CellObservation` and `Scenario` types in the mapping plan. These fields document rights; they do not replace reviewing the actual licence.

```ts
type Permission = "allowed" | "conditional" | "not_allowed" | "unresolved";

type SourceRelease = {
  id: string;                    // e.g. "WATER-06" plus a release suffix
  catalogueSourceId: string;     // e.g. "WATER-06"
  provider: string;
  product: string;
  version: string;
  doi?: string;
  documentationUrl: string;
  accessUrl: string;
  accessMethod: "api" | "stac" | "download" | "sdk" | "user_upload";
  evidenceType:
    | "satellite_retrieval" | "in_situ" | "reported"
    | "modelled" | "scenario_assumption";
  variables: Array<{
    id: string;
    unit: string;
    meaning: string;
    verticalSupport?: string;
    aggregation: string;
  }>;
  nativeSpatialSupport: string;  // pixel/grid/sample/basin/region; include scale
  coverageDescription: string;
  temporalCoverage: { start?: string; end?: string };
  retrievedAt: string;
  licence: {
    name: string;
    url: string;
    reviewedAt: string;
    attribution: string;
    commercialUse: Permission;
    publicDisplay: Permission;
    rawRedistribution: Permission;
    derivedRedistribution: Permission;
    notes: string;
  };
  upstreamAssetIds: string[];
};
```

Additional per-observation metadata should include time support, coverage fraction, QA state, aggregation version and original record IDs. For a composite product, preserve a list of contributing releases and their conditions. A derived output cannot silently discard restrictive upstream terms.

## 18. Route implementation notes

### Concrete upstream examples

These are documented route patterns, not a claim that authenticated downloads were run while preparing this catalogue. Replace placeholders with validated values; use the provider's current examples when implementing.

| Provider | Pattern / operation | Notes |
| --- | --- | --- |
| OpenFreeMap | `https://tiles.openfreemap.org/styles/liberty` | Public MapLibre style; keep attribution |
| NASA CMR | `https://cmr.earthdata.nasa.gov/search/collections.json` and `granules.json` | Add collection/version, bounding box, time and pagination; file access may require Earthdata Login |
| CDSE STAC | `https://stac.dataspace.copernicus.eu/v1/collections` and `/search` | Discover collection IDs; search by bounded region/time, then follow documented asset access |
| NASA POWER | `https://power.larc.nasa.gov/api/temporal/daily/point` | Example query fields: `parameters=ALLSKY_SFC_SW_DWN`, `community=RE`, `longitude`, `latitude`, `start=YYYYMMDD`, `end=YYYYMMDD`, `format=JSON`, `time-standard=UTC` |
| NASA FIRMS | `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}` | Use supported source codes and allowed day ranges; do not expose the token in exports/logs |
| NESO | `https://api.carbonintensity.org.uk/intensity` | Related `/generation` and `/regional` routes; match time/region/units |
| Copernicus Marine | `copernicusmarine.subset(...)` | Use the catalogue's exact dataset ID and bounded longitude/latitude/time/depth |
| CDS / ADS | Generated dataset request through the documented client | Dataset acceptance/authentication precede access; variable names differ by dataset |
| WCS / WFS / ArcGIS | The selected dataset's advertised service URL | Discover layer/coverage IDs and CRS first; do not invent one universal endpoint |

### Our proposed application routes

These belong to our application, not the upstream providers. They can initially be local functions reading prepared JSON.

| Route | Purpose |
| --- | --- |
| `GET /api/layers` | Layer definitions, units, time/coverage and source references |
| `GET /api/layers/:layerId/cells?bbox=west,south,east,north&resolution=6&time=...` | Batched values for a bounded viewport and display resolution |
| `GET /api/cells/:h3Id` | Cell inspector, observations and provenance |
| `GET /api/sources` | Source-release metadata and attributions without credentials |
| `POST /api/scenarios` | Save a new scenario or branch |
| `GET /api/scenarios/:id` | Restore a saved scenario |
| `POST /api/scenarios/:id/evaluate` | Deterministic scenario evaluation against a named baseline/model version |

Source adapters must preserve the difference between no coverage, no valid observations, a below-detection result and an actual zero. Errors should be visible in layer status, with an optional dated cache fallback.

## 19. Integration completion criteria

A source is integrated only when:

- Its exact release, access method and usage conditions are recorded.
- A small real sample has been retrieved successfully.
- Coordinates, units, scale factors, QA and missing values have been checked.
- H3 summaries can be traced back to original records/assets.
- The UI communicates native resolution, observation date and evidence type.
- Required attribution is visible and included in permitted exports.
- Raw and derived redistribution permissions are implemented separately.
- Missing coverage and upstream errors behave correctly.

The catalogue is deliberately broader than the hackathon build. Start with MAP-01, two or three baseline layers, explicit project assumptions and one convincing scenario comparison; expand adapters after that loop works.
