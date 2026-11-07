-- Scenarios are sets of changes over an immutable baseline (see CLAUDE.md).
-- H3 IDs are stored as 15-char lowercase hex strings, never as numbers.

CREATE TABLE scenario (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                text        NOT NULL CHECK (length(trim(name)) > 0),
    parent_scenario_id  uuid        REFERENCES scenario (id) ON DELETE SET NULL,
    baseline_revision   text        NOT NULL DEFAULT 'baseline-0',
    model_version       text        NOT NULL DEFAULT 'model-0',
    assumptions         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id    uuid             NOT NULL REFERENCES scenario (id) ON DELETE CASCADE,
    type           text             NOT NULL CHECK (type IN ('data_centre', 'solar', 'greenhouse')),
    name           text             NOT NULL DEFAULT '',
    -- Exact placement coordinate in WGS84 degrees, kept separate from the cell centre.
    latitude       double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude      double precision NOT NULL CHECK (longitude >= -180 AND longitude < 180),
    -- Canonical simulation cell containing (latitude, longitude).
    h3_id          text             NOT NULL CHECK (h3_id ~ '^[0-9a-f]{15}$'),
    h3_resolution  smallint         NOT NULL DEFAULT 6 CHECK (h3_resolution = 6),
    parameters     jsonb            NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz      NOT NULL DEFAULT now(),
    updated_at     timestamptz      NOT NULL DEFAULT now()
);

CREATE INDEX project_scenario_idx ON project (scenario_id);
CREATE INDEX project_h3_idx ON project (h3_id);
