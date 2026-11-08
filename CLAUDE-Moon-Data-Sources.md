# CLAUDE-Moon-Data-Sources.md — Moon data catalogue

Last reviewed: 2026-11-08. Status: **research findings only.** Nothing here has been downloaded into `data/` or wired into the app yet.

This is the Moon counterpart of [CLAUDE-Data-Sources.md](./CLAUDE-Data-Sources.md). It keeps the same rules: every layer has provenance, missing values are null (never zero), evidence types stay separate, and a detection is not a quantity. Source IDs use a `MOON-` prefix so they can share `data/raw/<ID>/` with the Earth sources.

**Verification.** ✓ means the URL was fetched on 2026-11-08 and returned the expected file type and size. ✓✓ means it was also re-checked directly during this review (27 key URLs). ✗ means it failed or needs a login. **U** means unverified.

**Licences.** Unless a row says otherwise, data from NASA, PDS, PGDA, LROC and USGS is US-government work with no copyright. Credit is requested (LROC: "NASA/GSFC/Arizona State University"; cite the product paper). Zenodo rows give their own licence (mostly CC BY 4.0). JAXA, ISRO and CNSA data have their own terms (see §10).

**Evidence codes.**
- **ORB**: orbital retrieval
- **MOD**: derived model
- **INS**: in-situ measurement or sample
- **REC**: reported record
- **PLAN**: planned or announced
- **ASSUMP**: scenario assumption

Transport and building figures carry one more tag:
- **[C]**: company or official claim
- **[K]**: contract value or NASA requirement
- **[M]**: measured or flown
- **[E]**: independent estimate
- **[D]**: derived here

---

## 1. What has changed (as of 8 Nov 2026)

**Artemis programme**
- **Artemis II flew** (1–10 Apr 2026), with a crew of four around the Moon.
- **Artemis III will not land.** On 27 Feb 2026 it was redefined as a crewed docking test in low Earth orbit with both commercial landers, around mid-2027.
- **The first crewed landing is Artemis IV, in 2028.** The lander (Starship or Blue Moon) has not been assigned.
- **Gateway is paused** (24 Mar 2026). NASA moved about $20B over 7 years to a south-pole "Moon Base". Without Gateway, the lander staging orbit is open again (near-rectilinear halo orbit vs low lunar orbit).

**Starship**
- **Starship V3 reached orbit for the first time** on Flight 14 (28 Sep 2026).
- **Ship-to-ship propellant transfer has not flown yet.** NASA's IAC-2026 slide puts it in Q1 2027.
- **Uncrewed demo landing** is around Q1 2028, with a 100 m landing-accuracy requirement.
- **SpaceX lunar cargo price.** SpaceX listed lunar-surface cargo at **US$100M per tonne, no earlier than 2028** (Oct 2025; seen through a secondary source because the SpaceX page was down).

**Landings and impacts**
- **No landing has been attempted in 2026.** The only new object on the Moon is a Falcon 9 upper stage that hit near Einstein crater on 5 Aug 2026.

**Delayed or cancelled missions**
- **Chang'e-7** (Shackleton rim): Aug 2026 launch scrubbed, now 2027.
- **Griffin-1**: Jan 2027.
- **IM-3** and **Blue Moon MK1**: Q1 2027.
- **Blue Ghost M2**: later in 2027.
- **VIPER** was revived in Sep 2025 and is on Blue Moon, late 2027.
- **APEX 1.0** (Schrödinger basin): contract ended Jul 2026.

**Data releases and access**
- **New since 2023:**
  - PGDA LOLA 20 m south-pole suite (Barker 2023) and north-pole suite (2025)
  - USGS 1 m south-pole NAC and ShadowCam image mosaics
  - Mini-RF 90 m polar radar mosaics (2025)
  - Chandrayaan-2 DFSAR polar radar mosaics (Nov 2025; PRADAN login required)
  - LEND neutron release 67 (Sep 2026)
- **The PDS Imaging Node shows a federal funding-lapse banner.** Mirror what we need early.

## 2. Spatial model on the Moon

### 2.1 Frame and coordinates
- **Frame.** Use **IAU_2015:30100**: Moon Mean-Earth frame (as LRO realised it, DE421) on a sphere of R = 1737.4 km, planetocentric, longitude positive east. LOLA, SLDEM2015, LROC, Diviner, USGS and the IAU Gazetteer all use it.
  - **Never mix in the principal-axis (PA) frame.** GRAIL gravity models are in PA, which is offset by under 1 km. That doesn't matter at res 6 but does at res 7 and above.
- **Longitudes come in two conventions:**
  - **0–360:** PDS LOLA/SLDEM files (`..._000_360`), Gazetteer `center_lon`, LROC `LON_360`.
  - **±180:** USGS GeoTIFFs and LROC `_180` shapefiles.
  - Normalise to ±180 before H3 indexing.
- **Heights.** Heights are relative to the 1737.4 km sphere, not a geoid.
  - PDS `float_img` heights are in **km**, with `OFFSET = 1737.4`.
  - The int16 IMG files use a 0.5 m scale. Always read `SCALING_FACTOR`.
- **Polar grids** are polar stereographic, in metres (IAU2000:30118 north, 30120 south). Convert pixel centres with pyproj before assigning H3 cells.
- **Time.**
  - Store UTC. Coordinated Lunar Time (LTC) is not defined yet; NASA's strategy is due 31 Dec 2026.
  - The Moon has no months: the 29.5-day synodic day and 1.54° tilt replace seasons. The Earth app's "month" slices become **lunar local-time bins** (Diviner has 24) and, at the poles, season × sun-longitude bins.

### 2.2 H3 works unchanged
H3 is defined on a unit sphere, so cell IDs are identical. Only areas and lengths scale:
- area × (1737.4 / 6371.0)² = **× 0.07437**
- length × **0.2727**

Areas below were computed with h3-py:

| Res | Moon avg area | Moon edge | Cells (whole Moon) |
|---|---|---|---|
| 3 | 921.7 km² | 18.8 km | 41,162 |
| 4 | 131.7 km² | 7.1 km | 288,122 |
| 5 | 18.8 km² | 2.7 km | 2,016,842 |
| **6** | **2.69 km²** | **1.0 km** | **14,117,882** |
| 7 | 0.384 km² | 0.38 km | 98.8 M |
| 8 | 0.055 km² | 0.15 km | 691.8 M |

Res 6 stays the simulation cell. The whole Moon (37.9 M km²) has the same 14.1 M res-6 cells as the whole Earth, so global Moon layers are the same size as the global Earth layers we already serve.

**Code that hard-codes Earth's radius and needs a body-aware area.** These calls take h3's km² or m² output directly. Switch them to `unit="rads^2"` × R² (h3-js: `UNITS.rads2`):
- [geo.py:64](backend/app/geo.py:64)
- [site_capacity.py:286](backend/app/site_capacity.py:286), used for site area, ring land and rainfall surplus
- [building_assess.py:67](backend/app/building_assess.py:67) and [:457](backend/app/building_assess.py:457)
- [routers/layers.py:19](backend/app/routers/layers.py:19), [:127](backend/app/routers/layers.py:127) and [:173](backend/app/routers/layers.py:173)
- [CellInspector.tsx:74](frontend/src/components/CellInspector.tsx:74)

[h3grid.ts:94](frontend/src/lib/h3grid.ts:94) is a ratio, so it is fine as long as both sides use the same radius.

### 2.3 MapLibre on the Moon (gotchas, maplibre-gl 6.16+)
1. **Only Web Mercator XYZ tiles work.**
   - NASA Moon Trek WMTS is plate carrée (2×1 tiles at z0) or polar stereographic, so MapLibre can't load it directly.
   - **Day one:** the LROC WMS with `{bbox-epsg-3857}` (MOON-MAP-01). It was tested and returns a correct WAC image with feature names in place.
   - **Production:** treat the lunar lon/lat GeoTIFF as EPSG:4326 → `gdalwarp -t_srs EPSG:3857` → PMTiles. The WAC 100 m mosaic needs z0–9, about 350k tiles (~3–6 GB WebP).
2. **Earth radius is hard-coded** (`earthRadius = 6371008.8`).
   - ScaleControl and `distanceTo` read 3.67× too large, so write our own scale bar.
   - raster-dem terrain needs `exaggeration ≈ 3.67` to show true proportions.
3. **Poles are smeared above ±85.05°.** Globe view stretches the edge tiles to the pole, which hides the core of the Artemis region (Shackleton is at 89.9°S). Options:
   - a polar-stereographic south-pole inset (Trek SP tiles or PGDA COGs in a deck.gl OrthographicView); or
   - a rotated-pole basemap.

   This is the biggest UI decision (§12).
4. Turn off atmosphere and sky (black background), and self-host glyphs for the Gazetteer labels.

### 2.4 Data regions (the Moon version of `arizona` / `uk`)
- **Global by default.** The whole Moon at res 6 is no bigger than the global Earth layers.
- **Raw files over 100 MB** follow the existing `_global_tmp` pattern: download, aggregate to H3, delete the raw file, keep the Parquet. Under the Earth rule, a global LOLA file (1–4 GB) would be regional-only, so the rule needs this explicit Moon exception.
- **Finer than res 6 (res 7–9) only in regions:**
  - `south_pole`: latitude ≤ −80°. Covers every PGDA 20 m product, all 9 Artemis regions (Cabeus B at 82.3°S is the northernmost), Shackleton, and most planned landings.
  - Optional second region `tranquillitatis`: W 10, S −10, E 40, N 30. Includes the Apollo 11, 16 and 17 sites, high-titanium mare (oxygen feedstock) and the Taurus–Littrow dark-mantle deposits.

---

## 3. Earth layer → Moon layer

| Earth app layer | Moon replacement | IDs |
|---|---|---|
| OpenFreeMap basemap | LROC WAC 100 m mosaic (WMS now, PMTiles later); Kaguya TC low-sun mosaic as an alternative | MAP-01, MAP-03 |
| Photon place search | IAU Gazetteer (9,087 named features, with LAC quadrangle codes) | PLACE-01 |
| Natural Earth countries/states, US counties | Mare polygons (by name), LAC quadrangles (from Gazetteer `quad_code`), Unified Geologic Map units | PLACE-02, GEO-01 |
| Copernicus DEM elevation/slope | LOLA + SLDEM2015 (global), PGDA 20 m (south pole) | TOPO-01..04 |
| ESA WorldCover land cover | Unified Geologic Map unit (majority per cell) + mare/highland | GEO-01, PLACE-02 |
| NASA POWER solar GHI | LOLA polar sunlit fraction (65–90°) + **computed global layer** (kWh/m²/day on a tracking panel, longest night) | SUN-01..04 |
| ERA5/POWER temperature, warmest/coldest month | Diviner Tmax/Tmin/Tmean in 24 local-time bins; polar seasonal maps | THERM-01..03 |
| Rainfall, wind, SMAP, GRACE, SWOT, rivers, HydroBASINS | **No analogue**: no water cycle. Water becomes *ice* | — |
| WRI Aqueduct water stress, water access | Ice-stability depth, hydrogen ppm, shadowed regions, PSR volatiles database | ICE-01..05 |
| SoilGrids (pH, clay, organic carbon, N, bulk density) | Regolith composition (FeO, TiO₂, Th, Al), rock abundance, H-parameter (regolith density) | COMP-01..05, THERM-04 |
| USGS MRDS mineral sites, NASA EMIT | Lunar Prospector gamma-ray elements, WAC TiO₂, Diviner CF mineralogy, Kaguya MI; sample sites as assays | COMP-* |
| GHSL/WorldPop population, built-up, "market access" | No residents. Replaced by **distance to a hub** (planned base, landing sites, other buildings) and the record of human-made objects | SITE-01, SITE-04 |
| Power plants, datacentres, dams, airports, seaports | LROC anthropogenic objects (71), planned missions file, laser retroreflectors | SITE-01..03 |
| HV lines, substations, submarine cables | Comms: direct-to-Earth visibility + relay coverage | SUN-03, SITE-05 |
| USGS earthquakes (live) | Apollo moonquake catalogue + young lobate scarps. **Live analogue:** NOAA SWPC proton flux (solar particle event alert) | HAZ-01, -02, -07 |
| NASA FIRMS fires | No analogue. Nearest hazards: new impact craters, plume ejecta | HAZ-04, SITE-06 |
| CAMS / Sentinel-5P air quality, "dust" | No atmosphere. Dust = landing-plume ejecta (a keep-out constraint) | SITE-06 |
| NDVI, GEDI, ECOSTRESS, PACE | No analogue | — |
| Open-Meteo point weather | Space weather: NOAA SWPC, PREDICCS dose | HAZ-07 |
| GIBS / Sentinel-2 imagery | Moon Trek layers, LROC NAC / ShadowCam 1 m south-pole mosaics | MAP-02, -04 |
| Electricity price (USD/kWh) | **Derived** $/kWh: delivered mass of the power plant ÷ lifetime energy | TRANS §8 |
| Water price (USD/m³) | Imported $/kg (= delivered cost) vs ice-mined $/kg | TRANS §8 |
| NESO carbon intensity | No analogue | — |
| "Neighbours" factor (homes nearby) | Keep-out rings: heritage sites (2 km / 0.5 km), landing-plume radius (≥2 km), Artemis Accords safety zones | SITE-06, -07 |

---

## 4. Catalogue: basemap, terrain, geology, places

### 4.1 Basemap and imagery

| ID | Dataset | Access | Notes | Pri |
|---|---|---|---|---|
| **MOON-MAP-01** | LROC Lunaserv WMS (IM-LDI/ASU), 351 layers | ✓✓ `https://wms.im-ldi.com/?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=luna_wac_global&STYLES=&SRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png` | Works in MapLibre as a raster source today (CORS `*`). Overlay layers include `luna_nomenclature` (labels), `luna_mare`, `luna_psr_81s`, `luna_polar_illumination` and `luna_wac_dtm_hillshade`. AccessConstraints "None". Cut off at ±85°. The old `webmap.lroc.asu.edu` host returns a 301 redirect | **P0** (day one) |
| **MOON-MAP-02** | LROC WAC Global Morphologic Mosaic 100 m (Jun 2013) | ✓✓ `https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LROC-WAC_Mosaic_global_100m_June2013.tif` (5.96 GB) | Source for our own Web Mercator PMTiles (z0–9). ORB | **P0** |
| MOON-MAP-03 | Kaguya TC Morning / Evening / Ortho mosaics, 64 ppd (~474 m) | ✓ `https://planetarymaps.usgs.gov/mosaic/Lunar_Kaguya_TC_Morning_Global_64ppd_v04.tif` (0.53 GB) | Low-sun alternative basemap. JAXA credit | P1 |
| MOON-MAP-04 | USGS LMAP south-pole COGs: NAC 1 m controlled mosaic (77 GB), ShadowCam 1 m (19.9 GB), LOLA 5 m DEM (4.2 GB) | ✓ `https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Lunar_safed/LMAP/SouthPolar/` | Close-up inset for the Artemis area; ShadowCam shows inside shadowed craters | P2 |
| MOON-MAP-05 | NASA Moon Trek WMTS (1,096 equatorial layers; SP/NP polar sets) | ✓ `https://trek.nasa.gov/tiles/Moon/EQ/{LAYER}/1.0.0/default/default028mm/{z}/{y}/{x}.jpg`; catalogue `https://trek.nasa.gov/moon/TrekServices/ws/index/eq/searchItems?start=0&rows=2147483647` | Plate carrée / polar stereographic, so not usable directly in MapLibre. Good for a polar inset (SP tiles) and for previewing products, e.g. `Kaguya_TCortho_Mosaic_Global_4096ppd` (z10) or `CE2_GRAS_DOM_07m` (z11) | P1 (polar inset) |
| MOON-MAP-06 | OpenPlanetaryMap Moon basemap and hillshade (XYZ) | ✓✓ `https://cartocdn-gusc.global.ssl.fastly.net/opmbuilder/api/v1/map/named/opm-moon-basemap-v0-1/all/{z}/{x}/{y}.png` | Web Mercator but only useful to z6; no licence stated | P2 |

### 4.2 Terrain (replaces Copernicus DEM)

| ID | Dataset | Res / coverage | Access (size) | Pri |
|---|---|---|---|---|
| **MOON-TOPO-01** | **SLDEM2015** (LOLA + Kaguya TC merge; Barker 2016; PGDA product 54) | 59 m native (effective 60–100 m), 60°S–60°N | ✓✓ PDS 128 ppd float: `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/sldem2015/global/float_img/sldem2015_128_60s_60n_000_360_float.img` (2.83 GB). 512 ppd GeoTIFF also available (22.65 GB) | **P0** |
| **MOON-TOPO-02** | **LOLA LDEM 128 ppd** (global) | 237 m | ✓✓ `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/float_img/ldem_128_float.img` (4.25 GB). 64 ppd is 1.06 GB; 16 ppd is 66 MB | **P0** (\|lat\| > 60°) |
| MOON-TOPO-03 | **PGDA LOLA south-pole suite** (Barker 2023, *PSJ* 4:183, product 90): DEM, slope, roughness, Hurst exponent, PSR raster and shapefile; north-pole suite is product 98 (2025) | 20 m (10–240 m variants), 80–90° | ✓ `https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/` (`LDEM_80S_20MPP_ADJ.TIF` 2.7 GB, `LDSM_…` 3.8 GB) | **P1** (res 7–9 in `south_pole`) |
| MOON-TOPO-04 | LOLA slope and roughness grids (`ldsm_16`, `ldrm_*`, polar `ldsm_75s_120m`, …) | 16–32 ppd global; polar | ✓ `.../lola_gdr/cylindrical/img/`, `.../polar/img/` | P1 (check our own slope) |
| MOON-TOPO-05 | Landing-site DEMs at 5 m: PGDA product 78 (Barker 2021); shape-from-shading DEMs (Bertone, Dec 2025, PGDA product 104, Zenodo 17954508, CC BY 4.0) | 5 m, candidate sites | ✓ | P2 |
| — | Chang'e-2 20 m DEM / 7 m image map | global | CNSA CLPDS, registration required | GATED |

**Pipeline for the res-6 elevation/slope layer:**
1. **Inputs:** SLDEM2015 128 ppd for \|lat\| ≤ 60°, LOLA 128 ppd beyond 60°, and PGDA 20 m for the south cap. Wrap them in a GDAL VRT on IAU_2015:30100 and convert km → m.
2. **Slope:** compute at native resolution with metric spacing (R = 1,737,400 m), in 10° tiles with a halo. Above 75°, work in polar stereographic, or check against the published LDSM grid.
3. **Assign cells:** h3ronpy, or pyproj → `h3.latlng_to_cell`.
4. **Aggregate per cell with DuckDB:** elevation mean/min/max/std, slope mean and p90, and the fraction of the cell under 5°, 10° and 15° slope.
5. **Output:** about 200–400 MB of Parquet; a few hours on a laptop.

Record the ~237 m slope baseline in provenance: it understates slope at lander scale.

### 4.3 Geology, craters, gravity

| ID | Dataset | Access | Use | Pri |
|---|---|---|---|---|
| **MOON-GEO-01** | **USGS Unified Geologic Map of the Moon 1:5M, GIS v2** (Fortezzo et al. 2020) | ✓✓ `https://asc-astropedia.s3.us-west-2.amazonaws.com/Moon/Geology/Unified_Geologic_Map_of_the_Moon_GIS_v2.zip` (224 MB) | Unit polygons + majority unit per cell (the "land cover" analogue). Dark-mantle units stand in for the pyroclastic layer. REC (compilation) | **P0** |
| MOON-GEO-02 | Robbins 2018 crater database (~1.3 M craters, ≥1–2 km) | ✓ `https://asc-astropedia.s3.us-west-2.amazonaws.com/Moon/Research/Craters/Ancillary/Catalog_Moon_Release_20180815_shapefile180.zip` (137.5 MB) | Crater density per cell; point layer | P1 |
| MOON-GEO-03 | GRAIL crustal thickness (Wieczorek 2013, models 1–4) | ✓ `https://zenodo.org/records/997347` (BSD-3) | Res 3–4 context. PA frame | P1 |
| MOON-GEO-04 | LU5M812TGT crater catalogue (La Grassa 2024, machine learning, >5 M craters ≥0.4 km) | ✓ `https://zenodo.org/records/13990480` (580 MB CSV, CC BY 4.0) | Denser crater counts | P2 |
| MOON-GEO-05 | Regolith thickness (Rajšić et al. 2026, 346 craters; ~6 m highlands, ~4 m maria) | ✓ `https://github.com/mattjsquared/lunar-surface-regolith` (GPL-3.0) | Points → coarse interpolation (mark MOD) | P2 |
| MOON-GEO-06 | LROC 5–20 km crater polygons (Povilaitis) | ✓ `https://data.lroc.im-ldi.com/lroc/view_rdr/SHAPEFILE_LROC_5TO20KM_CRATERS_SPOLE` | — | P2 |

### 4.4 Places and divisions

| ID | Dataset | Access | Notes | Pri |
|---|---|---|---|---|
| **MOON-PLACE-01** | **IAU/USGS Gazetteer of Planetary Nomenclature, Moon centre points** | ✓✓ `https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip` (23.8 MB, rebuilt nightly) | 9,087 features. Fields: name, approval date, diameter_km, `center_lat`, `center_lon` (0–360), type, `quad_code` (LAC-nn), link. Includes 6 official "Statio" landing-site names. Serves place search, labels and LAC grouping. Convert to GeoJSON (the DBF is bloated) | **P0** |
| **MOON-PLACE-02** | LROC global mare polygons (65°S–65°N, `MARE_NAME`) | ✓✓ `https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/LROC_GLOBAL_MARE/LROC_GLOBAL_MARE_180.ZIP` (8.75 MB) | Mare/highland boundary and named "regions" (our Natural Earth equivalent) | **P0** |
| MOON-PLACE-03 | Named-feature polygons from OPM (8,790) | ✓ `https://opmbuilder.carto.com/api/v2/sql?q=select * from opm_301_moon_nomenclature_polygons&format=GeoJSON` | Extents for search hits | P2 |
| — | LAC quadrangle grid (144) / basin catalogue | No file found. Use `quad_code`, or generate the grid from the LAC definition | | P1 (generate) |

---

## 5. Catalogue: sunlight, Earth visibility, temperature

### 5.1 Sunlight (replaces NASA POWER)

| ID | Dataset | Res / coverage | Access | Pri |
|---|---|---|---|---|
| **MOON-SUN-01** | **LOLA average solar illumination** `AVGVISIB_{65,75,85}{N,S}_{240,120,060}M_201608` (Mazarico 2011; PGDA 69) | 240/120/60 m, 65–90°. Fraction of time the sun is visible, 0–1 (INT16 × 4e-5). 18.6-yr average, no time variants. MOD | ✓✓ `https://pgda.gsfc.nasa.gov/data/MoonIllumination/AVGVISIB_65S_240M_201608.TIF` (60 MB). **Use the plain `.TIF`; the `_COG.TIF` links return an HTML page (✗).** IMG mirror: `https://imbrium.mit.edu/EXTRAS/ILLUMINATION/IMG/` | **P0** |
| **MOON-SUN-02** | **Permanently shadowed regions (PSR):** `LPSR_*_201608` raster (65–90°) and the Barker 2023/2025 20 m polygons (1,531 south PSRs > 1 km²) | 20–240 m, poles | ✓✓ `https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LPSR_80S_20MPP_ADJ_1km2.SHP` (20.7 MB); north `…/LOLA_20mpp_NP/LPSR_80N_20MPP_ADJ.SHP` | **P0** |
| **MOON-SUN-03** | **LOLA average Earth visibility** `AVGVISIB_*_201608_EARTH` | Same grids as SUN-01; fraction of time any part of Earth's disc is visible | ✓✓ `https://pgda.gsfc.nasa.gov/data/MoonIllumination/AVGVISIB_65S_240M_201608_EARTH.TIF` | **P0** (comms factor) |
| **MOON-SUN-04** | **Computed global sunlight and Earth visibility** (ours) | Every res-6 cell | See below | **P0** (compute) |
| MOON-SUN-05 | LOLA sky visibility `SKYV_65{N,S}_240M` (sr; flat ground = 2π) | 240 m, 65–90° | ✓ `https://imbrium.mit.edu/EXTRAS/ILLUMINATION/IMG/SKYV_65S_240M.IMG` | P1 (radiation and thermal view factor) |
| MOON-SUN-06 | LROC WAC observed polar illumination (Speyerer & Robinson 2013) | 100 m, 88–90° | ✓ PDS LROC `WAC_POLE_ILL_*` | P2 (validation) |

**Below 65° no product exists, so we compute it (MOON-SUN-04).**
- **Physics:** S = 1361 W/m² × (1 AU / r)². Monthly mean on flat ground = S·cos φ / π.
  - At the equator that is 433 W/m² = **10.4 kWh/m²/day** (per Earth day).
  - A two-axis tracking panel gets S × the fraction of time lit: **16.3 kWh/m²/day** at the equator, **~27 kWh/m²/day** on a polar ridge lit 83% of the time.
  - Earth's best deserts get about 6–7 kWh/m²/day.
- **Method:**
  1. Sub-sample each res-6 cell at res 8.
  2. Build 72-azimuth horizon masks from SLDEM/LOLA.
  3. Step the sun and Earth hourly with SPICE (DE440, `moon_pa_de440_200625.bpc`, `moon_de440_250416.tf`): one year below ~60° latitude, the full 18.6-yr cycle closer to the poles.
- **Outputs per cell:** fraction of time lit; kWh/m²/day for tracking, vertical and horizontal panels; longest night in hours; fraction of time Earth is visible.
- **Quality check:** reproduce SUN-01 in the 65–80° overlap.
- **Store the tracking or vertical-panel figure, not horizontal irradiance**, which is near zero at the poles.
- **Mast-height sunlight (2 m, 10 m) and longest continuous darkness have no public grid.** Compute them from the 20 m DEM (TOPO-03) for the vertical solar array building type. Published values at Connecting Ridge (Gläser 2014): 92.3% lit at 2 m, 95.7% at 10 m, longest dark spell 3–5 days. The best surface sites are lit 69.5–82.9% of the time (Gläser 2018).

### 5.2 Temperature (replaces warmest/coldest month)

| ID | Dataset | Res / coverage / time variants | Access | Pri |
|---|---|---|---|---|
| **MOON-THERM-01** | **Diviner Global Cumulative Product** v002 (Williams 2017): bolometric and channel temperatures, K | 0.5° × **96 local-time bins**, global, 2009–2015. ORB | ✓✓ `https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/global_cumul_avg_cyl_00n10n_002.tab` (18 latitude-band tables × 156 MB). Quick-start rasters: ✓ `https://luna1.diviner.ucla.edu/~jpierre/diviner/level4_raster_data/diviner_tbol_max.tif` (`_min`) | **P0** |
| **MOON-THERM-02** | **Diviner seasonal polar temperatures** (Williams 2019): 6 seasons × 24 sun-longitude bins, plus ready-made summer/winter min/mean/max and "fraction of time < 110 K" | 240 m, 80–90°, 2009–2020. ORB | ✓ `https://luna1.diviner.ucla.edu/~jpierre/diviner/level4_polar/additional_maps/polar_south_80_summer_max.grd`; PDS `…/data_derived_pcp/seasonal/` | **P0** (poles) |
| **MOON-THERM-03** | **Rock abundance (RA) and rock-free regolith temperature (RT)** (Bandfield 2011) | **32 ppd ≈ 950 m (≈ one res-6 cell)** and 128 ppd, ±80°. RT has 10 night-time local-time bins. MOD | ✓✓ `https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gdr_l3/cylindrical/img/dgdr_ra_avg_cyl_032_img.img` (88 MB) | **P0** (RA), P1 (RT) |
| MOON-THERM-04 | H-parameter: depth over which regolith density increases (Hayne 2017) | 128 ppd, ±70°. MOD | ✓ `https://pds-geosciences.wustl.edu/lunar/urn-nasa-pds-chang_e_microwave_processed/miscellaneous/hpar_global_128ppd.fits` (1.65 GB) | P1 |
| — | Subsurface reference temperature: ~252–256 K at about 1 m depth (Apollo 15/17 heat-flow probes, Langseth 1976) | Constant. INS | — | P0 (constant) |

---

## 6. Catalogue: water ice and volatiles (replaces water access, Aqueduct, rivers)

| ID | Dataset | Measures / depth sensed | Res / coverage | Access | Pri |
|---|---|---|---|---|---|
| **MOON-ICE-01** | **Diviner Polar Resource Product** PRP-V2.0 (Paige 2010) | `ice_depth` m (**−999 = not stable**, which must be stored as `ice_stable=false`, not null and not 0), `temp_avg`, `temp_max` K. MOD | ~2.9 M triangles per pole, ≥ ~76° | ✓✓ `https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/dlre_prp_south.tab` (605 MB per pole) | **P0** |
| **MOON-ICE-02** | **Lunar Prospector neutron hydrogen, half-degree** (Feldman 2001) | H in ppm; WEH wt% = ppm × 8.94e-4. Top ~0.5–1 m. ORB | 0.5° bins, but the **true footprint is ~45 km**: sample at the cell centre, never average across cells. Global, 1998–99 | ✓✓ `https://pds-geosciences.wustl.edu/missions/lunarp/reduced/hydrogenhd.dat` (518 KB, int16 × 10) | **P0** |
| **MOON-ICE-03** | **Lemelin et al. 2021 south-polar PSR volatiles database** | One record per PSR: M3 ice-detection counts, LP hydrogen, Diviner temperatures, H₂O/CO₂ stability, slopes, illumination, traverse distance | South-pole PSRs | ✓✓ `https://zenodo.org/records/4646092` (xls + shapefile, CC BY 4.0) | **P0** (the ice "occurrence record") |
| MOON-ICE-04 | Ice-table depth, Tmax, sublimation rate (Schorghofer & Williams 2020) | m, K. MOD | 240 m, 80–90° | ✓ `https://luna1.diviner.ucla.edu/~jpierre/diviner/level4_polar/24x6_240m/additional_maps/polar_south_80_zit_float32.tif` | P1 |
| MOON-ICE-05 | LEND south-polar PSR hydrogen (McClanahan 2024) and LEND counts (release 67, data to Jun 2026) | Neutron counts / derived H. ~1 m | South pole | ✓ `https://zenodo.org/records/14002739` (NASA Open Source Agreement); PDS `lro-l-lend-2-edr-v1` | P1 |
| MOON-ICE-06 | Surface-frost indicators: LAMP far-UV ratio (240 m, ≥80°) and LOLA 1064 nm albedo (1 km, ≥50°) | µm surface. ORB | Poles | ✓ `https://planetarydata.jpl.nasa.gov/img/data/lro/lamp/gdr/LROLAM_2001/DATA/RATIO/LAMP_80s_240mpp_ratio_albed_01.img`; ✓ `.../lola_gdr/polar/float_img/ldam_50s_1000m_float.img` | P1 |
| MOON-ICE-07 | Mini-RF radar ΔCPR (APL 2025, 90 m, polar) | S-band, ~1 m. **High radar ratio can also mean rough ground** | Poles + global | ✓ `https://asc-pds-individual-investigations.s3.us-west-2.amazonaws.com/moon_lro_mini-rf_mosaics_apl_2025/data/mini-rf_south_pole_deltacpr_offsetto49d_90mpp_simp_0c.tif` (0.74 GB) | P1 |
| MOON-ICE-08 | M3 global surface hydration (OH + H₂O ppm; Li 2023) | µm surface; **hydration, not ice**: keep as a separate layer | Global, 6 maps of 3 GB each | ✓✓ `https://asc-pds-individual-investigations.s3.us-west-2.amazonaws.com/moon_m3_lunarwater_li_2023/data/WaterMaps/M3_ppmWater_FirstHalfCentralMagnetotail.tif` (3.04 GB; 5 other phase maps alongside) | P1 |
| MOON-ICE-09 | LCROSS impact result: 5.6 ± 2.9 wt% H₂O at Cabeus (~84.68°S, 48.70°W) | INS (impact plume) | 1 point | ✓ PDS LCROSS | P1 (record) |
| — | Chandrayaan-2 DFSAR L-band polar mosaics (25 m, Nov 2025) | several metres deep | Poles | ✗ PRADAN login | GATED |
| — | Li 2018 M3 ice pixels | Released only as a PDF supplement; use ICE-03 instead | — | — | n/a |
| — | KPLO KGRS, Chang'e-7, VIPER | No public data yet | — | — | GATED / future |

**Per-cell layers this gives us:**
- hydrogen ppm / WEH (global, coarse);
- **water-ice likelihood** (poles only), gated by ICE-01 and supported by ICE-02/03/06/07;
- surface hydration, kept separate.

The 110 K cold-trap threshold (THERM-02) links temperature and ice.

---

## 7. Catalogue: composition, minerals, samples (replaces SoilGrids, MRDS, EMIT)

| ID | Dataset | Measures | Res / coverage | Access | Pri |
|---|---|---|---|---|---|
| **MOON-COMP-01** | **Lunar Prospector GRS reduced products** | **Half-degree:** Th ppm, FeO wt%. **2°:** Ti, K, **Sm** (rare-earth proxy). **5°:** O, Si, Al, Fe, Mg, Ca, Ti, U, K, Th. Top tens of cm. ORB | Global; true footprint 45–150 km, so sample at cell centre and store `native_res_km` | ✓✓ `https://pds-geosciences.wustl.edu/missions/lunarp/reduced/thoriumhd.dat` (also `ironhd`, `titanium2d`, `oxygen5d`; 518 KB each). **Use `titanium5d.dat`: the PDS page mislinks Ti 5° to the uranium file** | **P0** |
| **MOON-COMP-02** | **LROC WAC TiO₂** (Sato 2017) | TiO₂ wt% (ilmenite ≈ 1.9 × TiO₂). **A value of 1.0 means "< 2 wt%"; store it as censored.** ORB | 400 m, ±70° | ✓✓ `https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/DATA/SDP/WAC_TIO2/WAC_TIO2_E350N0450.IMG` (8 tiles × 146 MB) | **P0** |
| **MOON-COMP-03** | **Diviner Christiansen Feature (CF) mineralogy** (Lucey 2021): space-weathering-corrected CF, plagioclase / pyroxene / olivine | wt%, top ~mm. ORB | 32 ppd ≈ res 6, ±70° | ✓✓ `https://zenodo.org/records/4558194` and 4558235 (CC BY 4.0, 206 MB each) | **P0** |
| MOON-COMP-04 | LP GRS elemental abundances (Prettyman 2006) | Major elements + K, Th, U | 2°/5°/20° | ✓ `https://pds-geosciences.wustl.edu/lunar/lp-l-grs-5-elem-abundance-v1/lp_9001/data/lpgrs_high1_elem_abundance_2deg.tab` | P1 |
| MOON-COMP-05 | Kaguya Multiband Imager mineral maps (Lemelin): plagioclase, olivine, ortho- and clinopyroxene, FeO, optical maturity (OMAT) | wt% | **59 m, ±50°, 37.7 GB per map** | ✓ `https://planetarymaps.usgs.gov/mosaic/Lunar_MI_mineral_maps/` (JAXA credit) | P1 |
| MOON-COMP-06 | Space-weathering iron (npFe⁰; Trang 2020) | wt% | 30 ppd, ±60° | ✓ `https://pds-geosciences.wustl.edu/lunar/urn-nasa-pds-trang2020_moon_space_weathering/data/kaguya_mi_derived_30ppd_npfe.img` | P1 |
| MOON-COMP-07 | Clementine FeO; Kaguya GRS nuclide maps; M3 Level 2 reflectance | — | — | ✓ USGS / DARTS / PDS Imaging | P2 |
| **MOON-COMP-08** | **Sample chemistry: Astromat Synthesis** (moondb.org now redirects here) | Bulk chemistry of Apollo and Luna samples. INS | Sample sites | ✓ `https://astromat.org/synthesis` (API `api.astromat.org`). Location search is disabled, so join coordinates from SITE-01. Chang'e-5/6 values entered by hand from papers | **P0** (assays) |
| MOON-COMP-09 | LROC Lunar Pit Atlas: 278 pits with diameters and depths (Wagner & Robinson) | REC | ±30 m | ✓✓ `https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/LUNAR_PIT_LOCATIONS/LUNAR_PIT_LOCATIONS.CSV` (167 KB) | **P0** (shelter) |
| — | KREEP terrane, pyroclastic deposits, helium-3 | No downloadable files. **Derive:** KREEP from a Th contour of about 3.5–4 ppm (Jolliff 2000); pyroclastics from geologic-map dark-mantle units plus Gaddis 2003 tables; He-3 as a derived model from TiO₂ + maturity + solar-wind exposure. Label all as MOD | — | — | P1 / P2 |
| — | Chandrayaan-2 CLASS/IIRS, Chang'e IIM/GRS, KPLO KGRS, CE-6-calibrated oxides (2026) | — | — | ✗ login / CNSA terms | GATED |

**Ingest rules**
1. **Coarse orbital data (≥30 km footprint: LP, LEND, KGRS):** sample at the cell centroid.
2. **Fine data:** aggregate as mean, p90 and valid fraction.
3. **Store the sensing depth for every layer:**
   - near-IR, UV and laser: µm–mm
   - Diviner CF: ~mm
   - gamma: tens of cm
   - neutrons and S-band radar: ~1 m
   - L-band radar: metres
4. **Call enrichment "enriched", never "ore".** Lunar rare-earth levels are far below terrestrial ore grade.

---

## 8. Catalogue: hazards, radiation, space weather

| ID | Dataset | Access | Use | Pri |
|---|---|---|---|---|
| **MOON-HAZ-01** | **Apollo Passive Seismic Experiment expanded catalogue** (PDS4): 28 located shallow moonquakes (Nakamura 1979: date, lat, lon, magnitude), 106 deep-quake nests, artificial impacts, 13,057 events without locations. 1969–77. REC | ✓✓ `https://pds-geosciences.wustl.edu/Lunar/urn-nasa-pds-apollo_seismic_event_catalog/data/nakamura_1979_sm_locations.csv` | Historical point layer (replaces the USGS feed) | **P0** |
| **MOON-HAZ-02** | **LROC lobate scarps** (young thrust faults): polylines 60°N–60°S plus polar points | ✓✓ `https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/LOBATE_SCARPS/LOBATE_SCARPS_180.ZIP`; `…/POLAR_SCARP_LOCATIONS/POLAR_SCARP_LOCATIONS.CSV` | Distance-to-scarp per cell (seismic factor) | **P0** |
| MOON-HAZ-03 | Chang'e-4 measured surface radiation: 13.2 ± 1 µGy/h absorbed, **1,369 µSv/day dose equivalent** (~1.9× the ISS) (Zhang 2020) | Constant. INS | Global constant, adjusted by sky view (SUN-05) and pit proximity | **P0** (constant) |
| MOON-HAZ-04 | LROC new impact craters: 222 found by before/after imaging (Speyerer 2016; updated 2025-02) | ✓ `…/EXTRAS/SHAPEFILE/GLOBAL_NEW_CRATERS/GLOBAL_NEW_CRATERS_180.ZIP` | Point layer + impact-flux reference | P1 |
| MOON-HAZ-05 | Crustal magnetic field T2015_449 (Wieczorek 2018 from Tsunakawa 2015) | ✓ `https://zenodo.org/records/3873648/files/T2015_449.sh.gz` (CC BY 4.0; expand with pyshtools) | Informational only: deflects solar wind (lunar swirls) but **not** cosmic rays | P2 |
| MOON-HAZ-06 | LRO CRaTER radiation data | ✓ PDS PPI | Reference | P2 |
| **MOON-HAZ-07** | **Live space weather:** NOAA SWPC GOES proton flux JSON; UNH PREDICCS Moon dose | ✓✓ `https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json`; ✓ `https://prediccs.sr.unh.edu/` | Live solar-particle-event alert: the analogue of the earthquake feed and point weather | P1 |
| — | Chandrayaan-3 ILSA seismometer; NASA Meteoroid Engineering Model 3; OLTARIS; Bickel 2020 rockfall map (136,610); NELIOTA impact flashes | ✗ login / request / not public / site 404 | — | GATED |

**Status of new seismometers.** Chang'e-7's seismometer slipped to 2027. NASA's Farside Seismic Suite lost its lander contract (2025). Watters 2024 linked an M~5.3 shallow quake to the de Gerlache scarp, which sits in an Artemis region, with shaking out to ~40 km.

---

## 9. Catalogue: sites, missions, comms, keep-out (replaces infrastructure layers)

| ID | Dataset | Access | Notes | Pri |
|---|---|---|---|---|
| **MOON-SITE-01** | **LROC Anthropogenic Objects** (Wagner 2017): 71 landers, rovers, impact sites and reflectors, coordinates measured from orbit (±metres), updated 2026-08-14 | ✓✓ `https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/ANTHROPOGENIC_OBJECTS/ANTHROPOGENIC_OBJECTS_180.ZIP` (1.6 MB) | Fields: OBJECT_ID, VEHCL_NAME, MISSION, LATITUDE, LONGITUDE, RADIUS, UNCERTAIN, DATE. **Gotchas:** (1) Luna DATE is the *launch* date. (2) RADIUS is distance from the Moon's centre; elevation = RADIUS − 1,737,400 m. (3) Objects never seen from orbit are missing (Luna 2/9/13, some ascent stages, SMART-1); add them from Wikipedia (CC BY-SA, which has some coordinate errors) as REC | **P0** |
| **MOON-SITE-02** | **Planned missions and target regions, 2027–2030** (curated by us) | Seed from the thespacedevs API + sources below; every row gets an "as of" date and PLAN evidence | Includes the 9 Artemis regions (Oct 2024; still current per LPSC 2026). **No official polygons exist**: use anchor features + ~15 km boxes, or the Zenodo 17084058 candidate-site shapefile (CC BY 4.0) | **P1** |
| MOON-SITE-03 | Laser retroreflectors (geodetic benchmark points): Apollo 11/14/15, Lunokhod 1/2, Blue Ghost 1 NGLR, small reflectors on CH-3, SLIM, CE-6, IM-1/2 | PGDA product 100 (LOLA ranging success, CSV) | Analogue for substations / survey nodes | P1 |
| **MOON-SITE-04** | **NAIF SPICE kernels** (DE440, `moon_pa_de440_200625.bpc`, `moon_de440_250416.tf`, DSN station kernel) | ✓ naif.jpl.nasa.gov | Computes sun/Earth visibility, libration and relay line of sight (SUN-04, SITE-05) | **P0** |
| MOON-SITE-05 | Comms relay coverage | Computed from relay orbits: Queqiao-2; IM relays from IM-3 (2027); ESA Lunar Pathfinder (2027); Starship relay demo (2028) | Per-cell "relay coverage", with direct-to-Earth from SUN-03/04. LunaNet Interoperability Spec v5 (Jan 2025) documents the model | P1 |
| **MOON-SITE-06** | **Keep-out rules**: NASA 2011 heritage recommendations Rev A | ✓ `https://www.nasa.gov/wp-content/uploads/2017/10/617743main_nasa-usg_lunar_historic_sites_reva-508.pdf` | No landing within **2.0 km** of heritage landing sites, **0.5 km** of heritage impacts. Walking limits: Apollo 11 75 m, Apollo 17 225 m. Basis: Apollo-sized landers threw gravel 1.5 km and dust > 2 km/s. Generated as rings around SITE-01 → constraint (veto) factor | **P0** |
| MOON-SITE-07 | Artemis Accords §11 safety zones (78 signatories, latest Vietnam 28 Oct 2026) | ✓ nasa.gov/artemis-accords | No fixed radius. Model as a user-set radius around planned or placed buildings | P2 |

**Soft landings, measured coordinates** (LROC; lat, lon east). Use these as the seed for SITE-01's "successful landing" style. Every crewed site is included.
- **Apollo LMs:**
  - Apollo 11: 0.6742, 23.4731
  - Apollo 12: −3.0128, −23.4219
  - Apollo 14: −3.6459, −17.4719
  - Apollo 15: 26.1324, 3.6333
  - Apollo 16: −8.9734, 15.5011
  - Apollo 17: 20.1911, 30.7723
- **Uncrewed Soviet and US landers:**
  - Surveyor 1, 3, 5, 6 and 7
  - Luna 16, 17 (Lunokhod 1), 20, 21 (Lunokhod 2), 23 and 24
- **Chang'e:**
  - Chang'e 3: 44.1214, −19.5117
  - Chang'e 4: −45.4562, 177.5886
  - Chang'e 5: 43.0576, −51.9161
  - Chang'e 6: −41.6383, −153.9857
- **Other national and commercial landers:**
  - Chandrayaan-3: −69.3740, 32.3187
  - SLIM: −13.3160, 25.2510
  - IM-1: −80.1276, 1.4367
  - Blue Ghost M1: 18.5622, 61.8102
  - IM-2: −84.7906, 29.1957

The full list, with crash and impact sites, is in SITE-01.

**Planned 2027–2030 missions (PLAN; dates slip often):**

| Mission | Target | Date |
|---|---|---|
| Griffin-1 | Mons Mouton / Nobile | Jan 2027 |
| IM-3 | Reiner Gamma (~7.4°N, 59.0°W) | Q1 2027 |
| Blue Moon MK1 | Shackleton connecting ridge (~89.5°S) | Q1 2027 |
| IM-4 | Mons Mouton | 2027 |
| Blue Ghost M2 | far side | late 2027 |
| Blue Moon + VIPER | south pole (Mons Mouton) | late 2027 |
| Chang'e-7 | Shackleton rim (~88.8°S, 123.4°E; unofficial) | 2027 |
| Chandrayaan-4 | near the Chandrayaan-3 landing site | 2027–28 |
| Artemis IV / V | south-pole Artemis regions | 2028 |
| Blue Ghost M3 | Gruithuisen Domes | 2028 |
| PROMISE rover | south-pole PSRs | late 2028 |
| LUPEX | south pole | 2028 |
| Chang'e-8 | Leibnitz Beta (Mons Mouton plateau) | 2028–29 |
| Lanyue (China crewed) | not announced (Rimae Bode is an academic proposal) | before 2030 |
| Fission Surface Power | site not published | by 2030 |
| ILRS | south pole | ~2035 |

**Crowding hotspots:**
- **Mons Mouton:** IM-2 is already there; Griffin-1, IM-4, VIPER, two Artemis regions and Chang'e-8 are headed there.
- **Shackleton:** Chang'e-7 and Blue Moon MK1.

**Artemis region anchors** (centre of the anchor feature; each region is ~15 × 15 km on its rim or flank):

| Region | Anchor centre |
|---|---|
| Peak near Cabeus B | 82.26°S, 54.59°W |
| Haworth | 87.45°S, 5.17°W |
| Malapert Massif | 85.98°S, 1.67°W |
| Mons Mouton (two regions: Mons Mouton, Mons Mouton Plateau) | 84.60°S, 31.00°E |
| Nobile Rim 1 and Rim 2 | 85.28°S, 53.27°E |
| de Gerlache Rim 2 | 88.49°S, 88.35°W |
| Slater Plain | 88.08°S, 111.29°E |

---

## 10. Transport: Starship as the reference (MOON-TRANS)

Starship sets the default numbers. Blue Moon and NASA's CLPS robotic-lander contracts are the comparison cases. All figures were checked against the 2025–2026 sources listed at the end of this section.

### 10.1 Vehicle and mission parameters

| Parameter | Value | Tag | Source |
|---|---|---|---|
| Payload to the lunar surface | **100 t** (SpaceX claim); **15 t** (NASA cargo-variant requirement); 59–80 t (independent estimate) | C / K / E | Starship HLS (Wikipedia), IAC-26 HLS paper |
| Return payload | No public figure | — | — |
| Tanker flights per landing | 4–8 (Musk 2021), 14 (SpaceX bid), ~16 launches in total (GAO 2021), "high teens / ~20" (NASA 2023), "10-ish" (SpaceX 2024), ">10" (NASA OIG Mar 2026). **A range, not an average** | C / K / E | NASA OIG IG-26-004 |
| Propellant per tanker / lander capacity | ~150 t / ~1,200 t | C | — |
| Mission profile | Depot in low Earth orbit (LEO) → tankers every ~6 days (fuelling starts > 200 days before crew launch) → lander refuels → staging orbit (was NRHO, now under review) → surface. Can loiter up to 100 days | K | NASA OIG; IAC-26 |
| Δv budget | LEO→TLI 3.20; TLI→NRHO 0.43 or →polar LLO 0.90; NRHO↔LLO 0.69–0.89 (depends on site); LLO↔surface 1.87 km/s. **LEO→surface ≈ 6.0–6.2 km/s; surface→NRHO ≈ 2.6 km/s** | E / D | May, Qu & Merrill 2020; Whitley & Martinez 2015 |
| Site access | From NRHO, poles and the ±90° limbs are cheapest. Equatorial sites near the Earth-facing centre need up to **+188 m/s** outbound; NRHO→LLO→NRHO round trip ranges 1,366–1,758 m/s | E | May, Qu & Merrill 2020 |
| Contracts | HLS Option A $2.89B (2021) + Option B $1.15B (2022). OIG: ~$4.3B including ceilings; NASA lander spending $18.3B through FY2030 | K | NASA, OIG |
| Published price | **$100M per tonne = $100,000/kg**, NET 2028 | C | SpaceX (Oct 2025), via secondary report |
| Comparison prices | CLPS ≈ **$1M/kg** (Blue Ghost 1: $93.3M / ~94 kg; Astrobotic list $1.2M/kg). Blue Moon MK1 3 t; MK2 30 t one-way / 20 t reusable. Blue Origin LTV delivery $234M | K / C | Payload Research; Spaceflight Now May 2026 |

### 10.2 Delivered cost per kg: our "price" layer

[D] Formula: (tankers + depot + lander launches) × $/launch, plus any expended lander hardware, ÷ landed payload. Scenario controls should expose these four inputs (like the Earth stress multipliers). The defaults are the four cases:

| Case | Tankers | $/launch | Landed payload | Lander | **$/kg delivered** |
|---|---|---|---|---|---|
| Optimistic | 4 | $10M (SpaceX target) | 100 t | reused | **$600** |
| Central | 10 | $50M | 50 t | expended (+$100M) | **$14,000** |
| SpaceX list price | — | — | — | — | **$100,000** |
| Conservative | 20 | $100M | 15 t | reused | **$146,700** |
| (CLPS today) | — | — | — | — | ~$1,000,000 |

**Site multiplier [D].** Apply about 1.0 at the poles up to about 1.1–1.25 at worst-case equatorial sites. This comes from the Δv spread above at a specific impulse of ~375 s, assuming NRHO staging. It is an estimate; payload sensitivity to Δv is not linear.

**Derived Moon "utility prices" [D].** These count transport cost only: no hardware, operations or night storage.

| Item | Basis | Optimistic | Central | SpaceX list | Conservative |
|---|---|---|---|---|---|
| Electricity, fission ($/kWh) | 6 t reactor, 40 kWe, 10 yr, always on | $1.0 | $24 | $171 | $251 |
| Electricity, vertical solar array ($/kWh) | 154–222 kg per 10 kW; 70% capacity factor (polar ridge only), 10 yr | $0.15–0.22 | $3.5–5.1 | $25–36 | $37–53 |
| Water, imported ($/kg) | = delivered $/kg | $600 | $14,000 | $100,000 | $146,700 |
| Water, ice-mined (energy only) | 2.85 kWh/kg (2.6 heat + 0.25 electric) × $/kWh | — | ~$10–68 | — | — |
| Oxygen, from ilmenite (energy only) | 24.3 ± 5.8 kWh/kg × $/kWh | — | ~$85–580 | — | — |
| Crew consumables (open loop) | 5.2 kg per crew-day (NASA BVAD: O₂ 0.84 + water 2.5 + food 1.83 kg) | $3.1k | $73k | $520k | $763k |

The Earth app's real grid tariffs are replaced by this table. Price layers become per-cell: delivered $/kg × site multiplier, plus power $/kWh for whichever source the cell supports. Fission works anywhere; solar depends on SUN-01/04.

### 10.3 Landing plume and pads (a building type and a constraint)

**Ejecta exposure.** Hits per landing on a 1 km² exposed area follow LI(r) = 8·r^−1.9 for a 10 t lander (Wittal et al., AAS 20-511), with r in km. Scaled to a 100 t lander [D]:

| Distance | Hits |
|---|---|
| 1 km | ~34 |
| 2 km | ~9 |
| 5 km | ~1.6 |
| 10 km | ~0.4 |

Starship lands heavier than 100 t, so treat these as lower bounds.

**Keep-out radius.** NASA keeps the lunar terrain vehicles (LTVs) **~2 km** away during landings, and the 2011 heritage rule is also 2 km. **Default plume keep-out: 2 km, user-adjustable.** No official Starship figure exists.

**Pad engineering** (NASA/Purdue, Dec 2025), for a 100 t lander:
- 42.9 kPa plume pressure and **21.5 MW/m²** heat flux
- pad diameter = 3× the vehicle footprint
- ~0.36 m sintered-regolith slab for a 50 t lander

**Pad cost** (Metzger & Autry 2022): $229M at $300k/kg transport, $130M at $100k/kg, $47M below $10k/kg.

**Sources for §10:**
- NASA OIG IG-26-004 (Mar 2026): https://oig.nasa.gov/wp-content/uploads/2026/03/final-report-ig-26-004-nasas-management-of-the-human-landing-system-contracts.pdf
- Creech et al., IAC-26-B3.1: https://ntrs.nasa.gov/api/citations/20260008717/downloads/HLS%20IAC%202026%20FINAL.pdf
- May, Qu & Merrill 2020: https://ntrs.nasa.gov/api/citations/20200002920/downloads/20200002920.pdf
- Wittal et al. (plume ejecta): https://ntrs.nasa.gov/api/citations/20205003590/downloads/20_Wittaletal_LanderPlumeEjecta.pdf
- Landing pad (Dec 2025): https://ntrs.nasa.gov/api/citations/20250011152/downloads/Lunar%20Landing%20Pad_2025-12-06.pdf
- Metzger & Autry: https://arxiv.org/abs/2205.00378
- Ice extraction: Leger et al., PNAS 2025: https://pmc.ncbi.nlm.nih.gov/articles/PMC11874342/
- Starship flight 14 report (Sep 2026): https://www.satellitetoday.com/launch/2026/09/28/spacexs-starship-reaches-orbit-cuts-10-hour-mission-short-after-engine-issue/
- Artemis III timing: https://aerospaceamerica.aiaa.org/nasa-eyeing-year-end-tanking-test-and-summer-2027-launch-for-artemis-iii/
- SpaceX lunar price (secondary report): https://teslanorth.com/2025/10/12/spacex-starship-to-begin-moon-cargo-missions-in-2028-mars-flights-by-2030/
- LTV and Blue Origin delivery costs: https://spaceflightnow.com/2026/05/27/nasa-outlines-nearly-1-billion-investment-into-initial-moon-base-missions/

---

## 11. Building types for the Moon (preset seeds, MOON-BLD)

Use these the same way as the Earth templates: blank means unknown, never zero.

| Type | Figures | Tag |
|---|---|---|
| Crew habitat (Foundation Surface Habitat) | 12 t landed-mass limit; 4 crew, short stays; ~127 m³ (U); delivery NET FY2033 | K |
| Fission Surface Power | ≤ 6,000 kg; 40 kWe, 120 Vdc, 10 yr; dose ≤ 5 rem/yr above background at **1 km** (a keep-out). 2025 directive: **≥ 100 kWe**, launch-ready Q1 FY2030 | K |
| Vertical solar array tower (NASA VSAT) | 10 kW per array (a 50 kW class also exists); 45–65 W/kg → 154–222 kg; mast ≥ 5 m, goal 10 m (Astrobotic's is ~20 m); 10-yr south-pole life | K / C |
| Night-survival storage (regenerative fuel cell) | 10 kW through a 200 h night = 2,000 kWh | K / D |
| Ice-mining plant (thermal) | 2.6 kWh of heat + 0.25 kWh of electricity per kg of water; 2.78 kg/h needs 2.5–3.2 kW of heat | E |
| Propellant / liquid-oxygen plant | ~11.3 kWh/kg LOX; 2,450 t/yr of water → 450 t/yr of propellant (Kornuta 2019) | E |
| Oxygen from ilmenite (hydrogen reduction) | 24.3 ± 5.8 kWh/kg O₂ at 10 wt% ilmenite; ≈ 2.5 kg O₂ per tonne of regolith | E / D |
| Oxygen by carbothermal reduction (NASA CaRD) | ~75 kWh/kg in the lab; integrated prototype test Feb 2026 | M (U) |
| Molten regolith electrolysis (oxygen + Fe/Si/Al/Ti metals) | ~21 kWh/kg O₂ (one review gives 420, an outlier); mare feedstock → Fe/Ti, highlands → Si/Al | E |
| Landing pad | §10.3 | E |
| Regolith 3D printing (ICON Olympus) | $57.2M NASA contract, runs to 2028; no mass or power figures | K |
| Comms tower (Nokia LTE, flown on IM-2) | ~2 km range; ran about 25 min (Feb 2025) | C / M |
| Pressurised rover (JAXA/Toyota Lunar Cruiser) | 2 crew; 30–45-day trips; > 10,000 km lifetime; delivery NET FY2032 | K |
| Unpressurised rover (LTV) | ~10 km per crewed sortie, ~400 km lifetime; $220M each | K |
| Greenhouse, data centre (Lonestar), telescopes (LuSEE-Night, FarView) | Mostly blank: mass and power not public | — |
| Life support per crew-day (NASA BVAD Rev2) | O₂ 0.84 kg; drinking water 2.0 + food water 0.5 kg; food 1.83 kg | K (U) |

**Real-example cards:**
- Starship HLS
- Blue Moon MK2 ($3.4B per NASA vs ~$3.1B per OIG; 30 t one-way)
- Blue Moon MK1 (3 t)
- Fission Surface Power
- Honeybee LAMPS solar array (10 kW)
- LTVs
- Lunar Cruiser
- Foundation Surface Habitat
- LuSEE-Night

---

## 12. Proposed Moon suitability factors

These use the same method as `site_suitability.py`: nested bands, weights, and constraint vetoes. The bands come from the literature cited. The ones marked † are heuristics to tune against data percentiles after ingest.

| Factor | Data | Ideal | Good | Marginal | Unsuitable | Constraint for |
|---|---|---|---|---|---|---|
| `sunlit_fraction` | SUN-01/04 | ≥ 0.80 | 0.60–0.80 | 0.45–0.60 (every low-latitude site) | < 0.45 or in a PSR | solar |
| `longest_night_days` | SUN-04 | ≤ 5 | 5–10 | 10–15 | > 15 | solar, crewed |
| `earth_visible` | SUN-03/04 | ≥ 0.95 | 0.50–0.95 | 0.10–0.50 | < 0.10 without a relay | crewed, comms |
| `slope` | TOPO-01..03 | reuse the Earth bands per building type. Lander slope tolerance was **not confirmed** (gap) | | | | all |
| `thermal_swing_K`† | THERM-01/02 | ≤ 150 | 150–220 | 220–300 | Tmax < 110 K (hardware) | habitats, electronics |
| `rock_abundance` | THERM-03 | < 0.01 | 0.01–0.03 | 0.03–0.10 | > 0.10 | pads, construction |
| `scarp_distance_km` | HAZ-02 (+ HAZ-01) | > 100 | 40–100 | 10–40 | < 10 | habitats |
| `ice_depth_m` | ICE-01 | ≤ 0.1 | 0.1–0.5 | 0.5–1.0 | not stable | ice mining |
| `hydrogen_ppm` | ICE-02 | > 120 | 80–120 | — | < 80 (background; global mean ~47) | ice mining (supporting) |
| `tio2_wt` | COMP-02 | ≥ 9 | 6–9 | 3–6 | < 3 (use electrolysis instead) | oxygen from ilmenite |
| `feo_wt` | COMP-01/05 | ≥ 18 | 15–18 | — | — | metals (Fe), sintering bonus |
| `thorium_ppm` | COMP-01 | > 8 | 5–8 | 2–5 | < 2 | rare-earth prospecting ("enriched") |
| `plagioclase_wt` | COMP-03/05 | ≥ 85 | — | — | — | Al/Si metals |
| `heritage_keepout` | SITE-06 | outside | — | — | inside 2 km / 0.5 km ring | **veto** for everything |
| `plume_keepout` | SITE-06 + placed pads | outside | — | — | inside the user-set radius (default 2 km) | **veto** for everything except pads |
| `delivered_cost` | §10.2 × site multiplier | — | — | — | — | all (cost factor, like electricity price) |
| `in_psr` | SUN-02 | — | — | — | inside a PSR (solar, crewed) | **bonus** for ice mining |

Radiation is uniform across the surface (HAZ-03), so it is not a per-cell factor. Treat it as a design constant, with bonuses for low sky view and nearby pits.

---

## 13. Gaps, gated sources and conflicts

**Not public, or behind a login:**
- Chandrayaan-2/3 data on PRADAN: DFSAR, CLASS, IIRS, ILSA, APXS
- Chang'e data on CLPDS: CE-2 DEM/DOM, IIM, GRS, LND raw
- KPLO KGRS
- NASA Meteoroid Engineering Model (MEM), OLTARIS
- Bickel rockfall map

**Gated or restricted terms:** JAXA (credit), ISRO (registration), CNSA (restrictive terms). Check the terms before redistributing.

**No dataset exists:**
- a global sunlight grid below 65° (compute it)
- sunlight at mast height (compute it)
- a helium-3 grid (build a derived model)
- a pyroclastic GIS file and a KREEP boundary (derive them)
- official Artemis region polygons
- a Starship return-payload figure
- an official Starship plume keep-out distance
- habitat, greenhouse and data-centre power figures
- a confirmed lander slope tolerance

**Conflicts kept apart, not averaged:**
- Starship V3 payload to LEO: 100 t vs 150 t
- tanker count: 4–20
- HLS contract values: NASA vs OIG
- Gateway: "paused" vs "cancelled"
- Artemis IV: "early 2028" (NASA IAC slide) vs "mid-2028"
- MRE oxygen energy: 21 vs 420 kWh/kg

**Corrected during review:**
- The PGDA `.TIF` illumination files **do** download (one research pass said they didn't); only the `_COG.TIF` links fail.
- The central delivered-cost case is $14,000/kg once the depot launch is counted. The first draft said $13,000.

## 14. Suggested ingestion order

1. **Basemap:** MAP-01 (WMS, today), then MAP-02 → PMTiles. Place search and labels from PLACE-01.
2. **Elevation and slope at res 6:** TOPO-01 + TOPO-02.
3. **Sunlight and Earth visibility:**
   - poles: SUN-01, SUN-02, SUN-03;
   - global: compute SUN-04 with SITE-04 (SPICE).
4. **Temperature:** THERM-01 (global, local-time bins), THERM-02 (poles), THERM-03 (rock abundance).
5. **Ice:** ICE-01 (PRP ice depth), ICE-02 (LP hydrogen), ICE-03 (PSR database) + ICE-09 (LCROSS point).
6. **Composition:** COMP-01 (LP GRS), COMP-02 (TiO₂), COMP-03 (Diviner CF mineralogy).
7. **Records:** SITE-01 (objects) + SITE-06 (keep-out rings), HAZ-01/02 (quakes, scarps), COMP-09 (pits), COMP-08 (samples).
8. **Geology and regions:** GEO-01 (geologic map), PLACE-02 (mare polygons).
9. **Transport and price model** (§10) as scenario controls, plus the Moon building presets (§11).
10. **Later:** south-pole res 7–9 detail (TOPO-03, MAP-04), relay coverage (SITE-05), live space weather (HAZ-07), crater density (GEO-02).
