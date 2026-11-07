# New Worlds UI concept prompts

Generated with the built-in image generation tool. These are interface mockups with illustrative data, not implemented application screens. The stress-test image received the following targeted refinement after visual review.

### Stress-test chart refinement

```text
Use case: precise-object-edit of a ui-mockup.
Edit this existing New Worlds desktop UI screenshot. Preserve the ENTIRE screenshot exactly: all text, map, header, sidebar, colors, cards, typography, table, numbers and placement must stay unchanged except the horizontal bar plot inside the lower-left "Water budget" card.
Fix only that plot so its lengths match the numbers. Normal allocation is 800 m³, stressed allocation is 400 m³, and demand is 576 m³.
Draw the Normal teal bar full width representing 800. Draw the Stressed teal bar exactly HALF of the Normal bar's width, representing 400. Put the vertical dashed demand marker at 72% of the Normal bar's width (576/800), and extend this dashed marker across both rows. Preserve the label "Demand 576 m³" above it.
REMOVE the large orange dashed filled extension that currently reaches all the way to the right end of the Stressed bar row. Instead leave the rest of that row unfilled and show a compact amber text label "176 m³ unmet" below the stressed bar, inside the same Water budget card. No orange filled segment at all. Keep the right-side labels "800 m³" on the Normal row and "400 m³" on the Stressed row, aligned vertically. If necessary slightly tighten vertical spacing inside ONLY this water budget card to fit the small unmet-demand label. Do not change or remove anything else in the screenshot. The final interface must remain the same high-resolution polished readable layout.
```

## 01-define-building

```text
Use case: ui-mockup.
Create ONE exceptionally polished high-fidelity desktop web application screenshot for the existing project "New Worlds", an interactive Earth exploration and hypothetical building-planning sandbox. This is a finished product interface concept, not a landing page or wireframe.
Format: wide landscape approximately 16:10, ideally 1920x1200 or higher. Full-bleed straight-on screenshot, no physical laptop, no perspective, no outer frame, no watermarks or decorative presentation captions. All visible text crisp, highly legible and correctly spelled. Realistic 2026 product UI craft with excellent typographic hierarchy, aligned controls, restraint and generous useful whitespace.
Consistent design system across this series: warm ivory/off-white panels, dark graphite text, muted teal primary actions, pale sage highlights, amber for unknowns/warnings. Fine light gray borders, 10-12px corner radii, subtle shadows only on floating map surfaces, precise modern sans serif typography like Inter, mono or tabular figures for numbers. No gratuitous gradients, neon effects, purple, oversaturated heatmaps or excessive card grids. Small elegant outline icons with text labels. Calm GIS cartography: a sophisticated light sand/stone terrain map of the Phoenix metropolitan area with pale roads, faint contour/shaded mountains, restrained city labels and selective subtle hexagonal-cell outlines. Keep the map a dominant useful workspace.
Shared top header: small simple geometric globe mark and "New Worlds" left; navigation "Explore", "Build", "Scenarios"; a scenario selector "Phoenix expansion"; a small visible "Example scenario" chip indicating that all displayed site facts and figures are illustrative.
Data centre example throughout: named "Phoenix DC-01", IT capacity 1,000 kW, load 80%, PUE 1.4, period 30 days / 720 hours, WUE 1.0 L/kWh on IT energy. Computed facility demand 1.12 MW, electricity 806.4 MWh per 30 days, water 576 m³ per 30 days. Chosen illustrative site's assumed electricity capacity is 1.5 MW and assumed water allocation is 800 m³ per 30 days. Do not show hypothetical quantities as verified science.

SCREEN 1 — DEFINE THE BUILDING.
Make "Build" the active navigation. Main workspace has a substantial but uncluttered left panel about 430px wide and a large map on the right. The panel is a refined, progressive-disclosure building form. Header breadcrumb "Define → Find a site → Build", with Define active. Title "What would you like to build?" and smaller subtitle "Start with a template, then make it yours."
An understated template selector shows "Data centre" selected, with "Power station", "Water plant" and "Custom" as options. Name field "Phoenix DC-01". Small description field "A 1 MW computing facility near Phoenix."
Clearly titled expanded section "Compute & cooling" with neat paired input controls:
"IT capacity" 1,000 kW; "Expected load" 80%;
"PUE" 1.4; "Water intensity" 1.0 L/kWh;
"WUE basis" IT energy; "Period" 30 days.
Give PUE a small explanatory help line "Includes cooling and facility overhead." Use small "Your input" micro-labels sparingly to differentiate inputs from results.
Below are three tidy collapsed accordion rows "Footprint & materials", "Costs & staffing", "Emissions & lighting", each with subtle chevron. Footer primary full-width teal button "Find locations" and secondary quiet action "Save definition". Leave all controls breathable and comfortably readable, no overpacked spreadsheet of tiny text.
Map shows Phoenix, Tempe, Mesa and surrounding desert terrain, a discreet search field "Search a place", zoom controls, scale and tiny map attribution. No suitable sites have been selected yet. Bottom of the map holds one beautiful low horizontal summary surface titled "Calculated from your inputs" with three large values and small units:
"Facility demand" "1.12 MW"
"Electricity · 30 days" "806.4 MWh"
"Water · 30 days" "576 m³".
Small secondary line "Complete the remaining fields when known." Design should make the distinction between the user's building assumptions and the calculated resource requirements immediately intuitive. No location feasibility claim.

```

## 02-find-a-site

```text
Use case: ui-mockup.
Create ONE exceptionally polished high-fidelity desktop web application screenshot for the existing project "New Worlds", an interactive Earth exploration and hypothetical building-planning sandbox. This is a finished product interface concept, not a landing page or wireframe.
Format: wide landscape approximately 16:10, ideally 1920x1200 or higher. Full-bleed straight-on screenshot, no physical laptop, no perspective, no outer frame, no watermarks or decorative presentation captions. All visible text crisp, highly legible and correctly spelled. Realistic 2026 product UI craft with excellent typographic hierarchy, aligned controls, restraint and generous useful whitespace.
Consistent design system across this series: warm ivory/off-white panels, dark graphite text, muted teal primary actions, pale sage highlights, amber for unknowns/warnings. Fine light gray borders, 10-12px corner radii, subtle shadows only on floating map surfaces, precise modern sans serif typography like Inter, mono or tabular figures for numbers. No gratuitous gradients, neon effects, purple, oversaturated heatmaps or excessive card grids. Small elegant outline icons with text labels. Calm GIS cartography: a sophisticated light sand/stone terrain map of the Phoenix metropolitan area with pale roads, faint contour/shaded mountains, restrained city labels and selective subtle hexagonal-cell outlines. Keep the map a dominant useful workspace.
Shared top header: small simple geometric globe mark and "New Worlds" left; navigation "Explore", "Build", "Scenarios"; a scenario selector "Phoenix expansion"; a small visible "Example scenario" chip indicating that all displayed site facts and figures are illustrative.
Data centre example throughout: named "Phoenix DC-01", IT capacity 1,000 kW, load 80%, PUE 1.4, period 30 days / 720 hours, WUE 1.0 L/kWh on IT energy. Computed facility demand 1.12 MW, electricity 806.4 MWh per 30 days, water 576 m³ per 30 days. Chosen illustrative site's assumed electricity capacity is 1.5 MW and assumed water allocation is 800 m³ per 30 days. Do not show hypothetical quantities as verified science.

SCREEN 2 — FIND AND INSPECT A SITE.
Make Build active, breadcrumb "Define → Find a site → Build" with Find a site active. A 330px left sidebar shows title "Find a site" and subheading "Phoenix DC-01 · 30-day assessment". Small summary "1.12 MW power · 576 m³ water". A bounded area control "Phoenix metro" and simple button "Update search". Below, three beautifully laid-out candidate rows, no opaque numerical scores:
"A  Mesa East" with teal status "Meets 3 entered criteria", selected;
"B  Buckeye" with amber status "Needs water allocation";
"C  Chandler South" with muted rust status "Exceeds power budget".
Each row has one tiny map thumbnail and a restrained distance label, ample separation. A quiet line "Results use example data and your assumptions."
The dominant central/right map has geography legible, Phoenix west of Mesa, roads, desert hills. Show a small bounded patchwork of translucent teal/amber/gray hexagonal cells and exactly three tasteful lettered site pins A, B and C. Highlight A in teal with a selection ring. Do not carpet the whole world in hexagons. Map toolbar with search, Layers, 2D/3D and zoom. Small pill legend "Meets criteria", "Needs data", "Does not meet".
A floating 340px inspection panel on the right overlays only part of the map. Title "Mesa East", smaller "Site A · Example location". Three clear evaluated check rows:
"Power" required "1.12 MW" / available "1.50 MW", green check and a small readable "Assumed supply" badge;
"Water · 30 days" required "576 m³" / available "800 m³", green check and "Assumed allocation" badge;
"Slope" "1.8°" / limit "5°", green check, caption "Illustrative terrain value".
A softly tinted note explicitly says "Land ownership and permits not assessed." Another quiet status line "Meets your 3 entered criteria". Large teal button "Build here"; smaller back link "Edit building".
The hierarchy must make assumption provenance obvious, keep the map central, make each criterion auditable, and avoid promising actual legal or engineering feasibility. This is an elegant understandable working planning tool.

```

## 03-stress-test

```text
Use case: ui-mockup.
Create ONE exceptionally polished high-fidelity desktop web application screenshot for the existing project "New Worlds", an interactive Earth exploration and hypothetical building-planning sandbox. This is a finished product interface concept, not a landing page or wireframe.
Format: wide landscape approximately 16:10, ideally 1920x1200 or higher. Full-bleed straight-on screenshot, no physical laptop, no perspective, no outer frame, no watermarks or decorative presentation captions. All visible text crisp, highly legible and correctly spelled. Realistic 2026 product UI craft with excellent typographic hierarchy, aligned controls, restraint and generous useful whitespace.
Consistent design system across this series: warm ivory/off-white panels, dark graphite text, muted teal primary actions, pale sage highlights, amber for unknowns/warnings. Fine light gray borders, 10-12px corner radii, subtle shadows only on floating map surfaces, precise modern sans serif typography like Inter, mono or tabular figures for numbers. No gratuitous gradients, neon effects, purple, oversaturated heatmaps or excessive card grids. Small elegant outline icons with text labels. Calm GIS cartography: a sophisticated light sand/stone terrain map of the Phoenix metropolitan area with pale roads, faint contour/shaded mountains, restrained city labels and selective subtle hexagonal-cell outlines. Keep the map a dominant useful workspace.
Shared top header: small simple geometric globe mark and "New Worlds" left; navigation "Explore", "Build", "Scenarios"; a scenario selector "Phoenix expansion"; a small visible "Example scenario" chip indicating that all displayed site facts and figures are illustrative.
Data centre example throughout: named "Phoenix DC-01", IT capacity 1,000 kW, load 80%, PUE 1.4, period 30 days / 720 hours, WUE 1.0 L/kWh on IT energy. Computed facility demand 1.12 MW, electricity 806.4 MWh per 30 days, water 576 m³ per 30 days. Chosen illustrative site's assumed electricity capacity is 1.5 MW and assumed water allocation is 800 m³ per 30 days. Do not show hypothetical quantities as verified science.

SCREEN 3 — STRESS TEST THE SCENARIO.
Make "Scenarios" active. Title in content "Stress test" with subtitle "Phoenix expansion · 1 building · 30 days". Show saved hypothetical data centre Phoenix DC-01 at Mesa East on the map. Calm modern dashboard arranged around the geographic map, with a 320px left control sidebar, map taking most of the upper-right workspace, and a focused comparison surface across the lower-right portion.
Left panel section "Scenario controls", small text "Change assumptions. Keep the baseline." Four exceptionally legible sliders with direct numeric inputs:
"Water availability" "50%" active amber (baseline allocation 800 m³, stressed 400 m³);
"Power availability" "100%";
"Operating demand" "100%";
"Resource prices" "100%".
Neutral controls teal/gray, only reduced water amber. Footer "Reset controls" quiet button and a small saved-state indication.
At top of map an amber insight banner with prominent text "176 m³ water shortfall" and supporting text "Demand stays at 576 m³. Your allocation falls to 400 m³." The single data-centre marker is amber and selected; a compact popover says "Phoenix DC-01" / "Water constraint". Keep the map itself calm and geographically meaningful, no dramatic fake spreading pollution graphics.
The comparison surface below the map is titled "What changes" with small "Same buildings. Same 30-day period." It contains an especially clear horizontal water-budget comparison: "Normal" bar 800 m³ and "Stressed" bar 400 m³, a distinct reference marker labelled "Demand 576 m³", and amber deficit segment labelled "176 m³ unmet". The bar arithmetic and label placements must be correct.
Beside or below the chart, a restrained three-row comparison table with columns "Normal" and "Stressed":
"Electricity demand" "806.4 MWh" "806.4 MWh";
"Water demand" "576 m³" "576 m³";
"Water shortfall" "0 m³" "176 m³".
A small explanatory caption "Supply values are scenario assumptions." Maybe a subtle context strip above the chart shows "1 building" and "30 days", not a dozen generic KPI cards. Emphasize readable comparison, direct manipulation and one actionable shortage. Do not add an AI chat panel, invented financial projections or unrequested connection networks.

```

