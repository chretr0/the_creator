-- Building definitions, placed-building snapshots and new building types
-- (CLAUDE.Building-System.md sections 4 and 11). Additive only: V1 is never edited.

-- New predefined types. Existing data_centre / solar / greenhouse rows remain valid.
ALTER TABLE project DROP CONSTRAINT IF EXISTS project_type_check;
ALTER TABLE project ADD CONSTRAINT project_type_check
    CHECK (type IN ('data_centre', 'solar', 'greenhouse', 'power_station', 'water_plant', 'custom'));

-- A user's named, described and configured design. Editing it only affects future placements.
CREATE TABLE building_definition (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text        NOT NULL CHECK (length(trim(name)) > 0),
    description      text        NOT NULL DEFAULT '',
    type             text        NOT NULL
        CHECK (type IN ('data_centre', 'solar', 'greenhouse', 'power_station', 'water_plant', 'custom')),
    template_id      text,
    template_version integer,
    schema_version   integer     NOT NULL DEFAULT 1,
    -- Structured, validated inputs (BuildingStats); missing keys mean unknown, never zero.
    stats            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- Type-specific scalar parameters (same meaning as project.parameters).
    parameters       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- Location requirements (list of Criterion).
    criteria         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Placed buildings keep a self-contained snapshot of the definition used to create them, so
-- later definition edits or deletion never change them. NULL definition = legacy project, read
-- through the compatibility adapter with every new statistic unknown.
ALTER TABLE project
    ADD COLUMN definition           jsonb,
    ADD COLUMN source_definition_id uuid REFERENCES building_definition (id) ON DELETE SET NULL,
    -- Site-specific declared assumptions for this exact location (SiteAssumptions).
    ADD COLUMN site                 jsonb NOT NULL DEFAULT '{}'::jsonb;
