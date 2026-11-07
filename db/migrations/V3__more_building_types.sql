-- More predefined building types (energy, water, extraction, industry, agriculture, commercial,
-- public services, transport and waste). Additive only: earlier migrations are never edited and every
-- existing type stays valid. Keep this list in sync with app/building_models.py BuildingType.

ALTER TABLE project DROP CONSTRAINT IF EXISTS project_type_check;
ALTER TABLE project ADD CONSTRAINT project_type_check
    CHECK (type IN (
        'power_station', 'solar', 'wind_farm', 'hydro_plant', 'geothermal_plant', 'battery_storage',
        'hydrogen_plant', 'water_plant', 'wastewater_plant', 'mine', 'quarry', 'oil_gas_field',
        'factory', 'steel_mill', 'aluminium_smelter', 'cement_plant', 'chemical_plant', 'oil_refinery',
        'semiconductor_fab', 'farm', 'livestock_farm', 'greenhouse', 'vertical_farm', 'aquaculture',
        'food_processing', 'data_centre', 'office', 'retail', 'hotel', 'research_lab',
        'housing', 'hospital', 'school', 'university', 'stadium', 'airport',
        'seaport', 'warehouse', 'landfill', 'recycling_facility', 'waste_to_energy', 'custom'
    ));

ALTER TABLE building_definition DROP CONSTRAINT IF EXISTS building_definition_type_check;
ALTER TABLE building_definition ADD CONSTRAINT building_definition_type_check
    CHECK (type IN (
        'power_station', 'solar', 'wind_farm', 'hydro_plant', 'geothermal_plant', 'battery_storage',
        'hydrogen_plant', 'water_plant', 'wastewater_plant', 'mine', 'quarry', 'oil_gas_field',
        'factory', 'steel_mill', 'aluminium_smelter', 'cement_plant', 'chemical_plant', 'oil_refinery',
        'semiconductor_fab', 'farm', 'livestock_farm', 'greenhouse', 'vertical_farm', 'aquaculture',
        'food_processing', 'data_centre', 'office', 'retail', 'hotel', 'research_lab',
        'housing', 'hospital', 'school', 'university', 'stadium', 'airport',
        'seaport', 'warehouse', 'landfill', 'recycling_facility', 'waste_to_energy', 'custom'
    ));
