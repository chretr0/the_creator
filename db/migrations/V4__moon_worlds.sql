-- Moon worlds: every scenario lives on one body, and Moon worlds hold the Moon building types listed in
-- shared/moon_buildings.json. Additive only: earlier migrations are never edited, every existing scenario
-- becomes an Earth world and every existing type stays valid. Keep the Moon types in sync with
-- shared/moon_buildings.json and app/building_models.py MoonBuildingType.
-- building_definition types are unchanged: Moon buildings are never saved as building definitions.

ALTER TABLE scenario
    ADD COLUMN body text NOT NULL DEFAULT 'earth' CONSTRAINT scenario_body_check CHECK (body IN ('earth', 'moon'));

ALTER TABLE project DROP CONSTRAINT IF EXISTS project_type_check;
ALTER TABLE project ADD CONSTRAINT project_type_check
    CHECK (type IN (
        'power_station', 'solar', 'wind_farm', 'hydro_plant', 'geothermal_plant', 'battery_storage',
        'hydrogen_plant', 'water_plant', 'wastewater_plant', 'mine', 'quarry', 'oil_gas_field',
        'factory', 'steel_mill', 'aluminium_smelter', 'cement_plant', 'chemical_plant', 'oil_refinery',
        'semiconductor_fab', 'farm', 'livestock_farm', 'greenhouse', 'vertical_farm', 'aquaculture',
        'food_processing', 'data_centre', 'office', 'retail', 'hotel', 'research_lab',
        'housing', 'hospital', 'school', 'university', 'stadium', 'airport',
        'seaport', 'warehouse', 'landfill', 'recycling_facility', 'waste_to_energy', 'custom',
        'moon_habitat', 'moon_solar_tower', 'moon_fission', 'moon_storage',
        'moon_ice_mine', 'moon_oxygen_plant', 'moon_greenhouse', 'moon_landing_pad'
    ));
