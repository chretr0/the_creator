# Average electricity and water prices (PRICE-01)

Inputs for the *Prices* map layers (`electricity_price`, `water_price`). Built into H3 resolution-6 cells by
`scripts/prepare_utility_prices.py`:

```bash
uv run --no-project --with h3 --with shapely --with pyarrow --with numpy --with openpyxl --with babel --with certifi python -I scripts/prepare_utility_prices.py --fetch
```

## What a cell's value means

One **average** end-user price for the area the cell is in, converted to USD:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `elec_household` | USD/kWh | Residential electricity, normally including taxes |
| `elec_business` | USD/kWh | Commercial / non-household electricity (Eurostat: excluding VAT, which businesses recover) |
| `water_household` | USD/m³ | Drinking water + wastewater at ~15 m³/month, fixed charges spread in |
| `water_business` | USD/m³ | Same for non-domestic customers (few countries) |

The area is the country, or for electricity the state/province in the US, Canada and Australia.
A cell takes the area containing its centre; coastal cells whose centre is at sea take the land area they
overlap. Open sea and uninhabited territories are blank. Zoomed-out hexagons show the mean of their cells.

## Averaging rules

The app uses one rate per area, so every source is reduced to a single average:

- **Day/night (time-of-use):** hours-weighted mean of the periods, `(peak × peak hours + off-peak × off-peak hours) / 24`.
- **Tiered / block tariffs:** effective price at a typical use (household electricity ~250 kWh/month,
  water ~15 m³/month), fixed or standing charges included where the source gives them.
- **Seasonal tariffs:** annual mean.
- **Official statistics** (EIA, Eurostat) are revenue ÷ sales over all customers and tariffs, so day/night,
  seasonal and tiered rates are already averaged. Eurostat values are the mean of the two latest semesters.

## Sources, highest priority first

1. **U.S. EIA** Electric Power Annual table 2.10: average retail price by state, residential and commercial (public domain).
2. **Eurostat** `nrg_pc_204` / `nrg_pc_205`, all consumption bands (CC BY 4.0): EU, EEA and candidate countries.
3. **`research.csv`** (this folder): country/province figures compiled from regulators, utilities, EurEau,
   ADERASA, Hydro-Québec's price comparison and, as a fallback, the GlobalPetrolPrices aggregator. Each row cites
   its source, year, tax basis and method; water rows say whether wastewater is included and which city's
   utility stands in for the country.
4. **World Bank Doing Business 2020** price of electricity (2019, commercial warehouse): only where nothing
   newer exists for business electricity.

Prices are converted with the World Bank official exchange rate (`PA.NUS.FCRF`, annual average) for the price year.
Prices newer than that series (it lags a year or more) use the current rate from ExchangeRate-API (open.er-api.com),
shown as `FX spot <date>` in the basis line, so devaluations such as Malawi's (2023) or Ethiopia's (2024) are not missed. `data/prepared/utility_prices/areas.csv` lists every resolved area × metric with the
local price, currency, USD value, exchange rate and source, and each cell carries the same as a *basis* line.

## Known gaps and caveats

- Nothing is filled in where no source was found: those countries are grey (unknown), never zero.
  Ireland's household water is a sourced zero (no domestic charges).
- Water is mostly one utility's tariff (capital or largest city) per country, except in Europe (EurEau national figures),
  Latin America (ADERASA), Canada (CWWA national average) and the US (Bluefield 50-city average bill ÷ its 27 m³/month
  benchmark; Arizona uses the Phoenix tariff). Many rows are water only: the basis line says so.
- Research rows must be dated 2018–2026; older tariffs and announced-but-not-yet-effective ones are left out.
- Aggregator figures (GlobalPetrolPrices) are national averages they compute; check their terms before commercial use.
- Volatile currencies (e.g. ARS, NGN, EGP) convert poorly with an annual average rate.
- Canadian provincial household figures are Hydro-Québec's 1,000 kWh/month bill, above the ~250 kWh typical use.

## Updating `research.csv`

One row per code × metric, then re-run the script. Columns:

| Column | Content |
| --- | --- |
| `code` | ISO 3166-1 alpha-2 country (`KE`) or ISO 3166-2 subdivision (`CA-QC`, `AU-NSW`, `US-AZ`). A subdivision without a price uses its country's |
| `metric` | `elec_household`, `elec_business`, `water_household` or `water_business` |
| `price` | Plain number in the local currency (`currency` = `USD` when the source only gives USD) |
| `currency` | ISO 4217 code |
| `year` | Price period: `2025`, `2025-H1`, `2026-03` |
| `tax_basis` | `incl_tax`, `excl_vat`, `excl_tax` or `unknown` |
| `includes_wastewater` | Water rows: `yes`, `no` or `unknown` |
| `method` | How the average was formed (show the arithmetic for tariffs) |
| `source_name`, `source_url`, `notes` | Citation and caveats (which city or utility, subsidies, aggregator) |

Never enter a guessed or "typical" value: leave the row out and the area stays unknown. EIA and Eurostat rows win
over `research.csv` for the same area and metric; change the order in `resolve()` to override them.
