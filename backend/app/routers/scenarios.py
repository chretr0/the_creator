from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app import geo, moon_buildings
from app.building_calc import CalcInputError, validate_parameters
from app.building_models import DefinitionSnapshot, ResourceBudget, ScenarioAssumptions, SiteAssumptions
from app.db import transaction
from app.models import (
    Project,
    ProjectCreate,
    ProjectUpdate,
    Scenario,
    ScenarioBranch,
    ScenarioCreate,
    ScenarioSummary,
    ScenarioUpdate,
    WorldBody,
)

router = APIRouter(prefix="/api", tags=["scenarios"])

PROJECT_COLUMNS = (
    "id, scenario_id, type, name, latitude, longitude, h3_id, h3_resolution, "
    "parameters, definition, source_definition_id, site, created_at, updated_at"
)

# Scenario-assumption keys owned by the building system (ScenarioAssumptions, camelCase on the wire).
BUILDING_ASSUMPTION_KEYS = {"schemaVersion", "periodDays", "budgets", "stress"}
_SNAKE = {"schema_version": "schemaVersion", "period_days": "periodDays"}


def snapshot_of(row: dict) -> DefinitionSnapshot:
    """Compatibility adapter: a legacy project (NULL definition) reads as a snapshot with every new
    statistic unknown. Template defaults are never filled in."""
    if row.get("definition") is None:
        return DefinitionSnapshot(name=row["name"][:200], description="", template_id=row["type"])
    return DefinitionSnapshot.model_validate(row["definition"])


def project_out(row: dict) -> dict:
    return {**row, "definition": snapshot_of(row), "site": SiteAssumptions.model_validate(row.get("site") or {})}


def _validation_error(exc: ValidationError, loc: tuple) -> RequestValidationError:
    return RequestValidationError(
        [{**e, "loc": (*loc, *e["loc"]), "ctx": {k: str(v) for k, v in e.get("ctx", {}).items()}}
         for e in exc.errors(include_url=False)]
    )


def _split_assumptions(raw: dict) -> tuple[dict, dict]:
    """(building-system keys in camelCase, other legacy keys preserved as-is)."""
    own, other = {}, {}
    for k, v in raw.items():
        key = _SNAKE.get(k, k)
        if key in BUILDING_ASSUMPTION_KEYS:
            own[key] = v
        else:
            other[k] = v
    return own, other


def validated_assumptions(raw: dict) -> dict:
    """Validate the building-system keys through ScenarioAssumptions; keep other keys untouched."""
    own, other = _split_assumptions(raw)
    if not own:
        return other
    try:
        parsed = ScenarioAssumptions.model_validate(own)
    except ValidationError as exc:
        raise _validation_error(exc, ("body", "assumptions")) from exc
    return {**other, **parsed.model_dump(mode="json", by_alias=True)}


def scenario_assumptions(raw: dict | None) -> ScenarioAssumptions:
    own, _ = _split_assumptions(raw or {})
    try:
        return ScenarioAssumptions.model_validate(own)
    except ValidationError:
        return _salvage_assumptions(own)


def _salvage_assumptions(own: dict) -> ScenarioAssumptions:
    """Stored assumptions that no longer validate as a whole (e.g. saved before a rule existed):
    keep every part that is still valid instead of silently resetting everything to defaults.
    Invalid budgets are dropped; a plant listed in two pools of one kind stays only in the first."""
    out = ScenarioAssumptions()
    for key in ("period_days", "stress"):
        try:
            out = ScenarioAssumptions.model_validate({**out.model_dump(), key: own.get(_camel(key), own.get(key))})
        except ValidationError:
            pass
    seen: set[tuple[str, str]] = set()
    budgets = []
    for raw in own.get("budgets") or []:
        try:
            b = ResourceBudget.model_validate(raw)
        except ValidationError:
            continue
        keep = [pid for pid in dict.fromkeys(b.contributing_project_ids) if (b.kind, str(pid)) not in seen]
        seen.update((b.kind, str(pid)) for pid in keep)
        budgets.append(b.model_copy(update={"contributing_project_ids": keep}))
    return out.model_copy(update={"budgets": budgets[:50]})


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.title() for w in rest)


def assumptions_out(raw: dict | None) -> dict:
    """Stored assumptions with building-system defaults filled (period 30 days, neutral stress, no budgets)."""
    _, other = _split_assumptions(raw or {})
    return {**other, **scenario_assumptions(raw).model_dump(mode="json", by_alias=True)}


def _load_scenario(conn: Connection, scenario_id: UUID) -> dict:
    scenario = conn.execute("SELECT * FROM scenario WHERE id = %s", (scenario_id,)).fetchone()
    if scenario is None:
        raise HTTPException(404, "scenario not found")
    scenario["assumptions"] = assumptions_out(scenario["assumptions"])
    scenario["projects"] = [
        project_out(r)
        for r in conn.execute(
            f"SELECT {PROJECT_COLUMNS} FROM project WHERE scenario_id = %s ORDER BY created_at, id",
            (scenario_id,),
        ).fetchall()
    ]
    return scenario


def _check_parameters(type_: str, parameters: dict) -> None:
    """Moon types are checked against shared/moon_buildings.json (null = unknown); Earth types keep the
    Earth rules, where an unknown value is an absent key, never null."""
    try:
        if moon_buildings.is_moon_type(type_):
            moon_buildings.validate_parameters(type_, parameters)
        else:
            nulls = sorted(k for k, v in parameters.items() if v is None)
            if nulls:
                raise CalcInputError("; ".join(f"{k} must not be null (omit it when unknown)" for k in nulls))
            validate_parameters(type_, parameters)
    except CalcInputError as exc:
        raise HTTPException(422, f"invalid parameters: {exc}") from exc


def _scenario_body(conn: Connection, scenario_id: UUID) -> str:
    row = conn.execute("SELECT body FROM scenario WHERE id = %s", (scenario_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "scenario not found")
    return row["body"]


def _check_world(world_body: str, type_: str) -> None:
    """Moon types belong in Moon worlds and Earth types in Earth worlds."""
    if moon_buildings.is_moon_type(type_):
        if world_body != "moon":
            raise HTTPException(
                422, f"'{type_}' is a Moon building type: it can only be placed in a Moon world, not an Earth one"
            )
    elif world_body == "moon":
        raise HTTPException(
            422, f"'{type_}' is an Earth building type: this is a Moon world, which takes only Moon building "
                 f"types ({', '.join(moon_buildings.MOON_TYPES)})"
        )


def _no_definition_link(type_: str) -> None:
    if moon_buildings.is_moon_type(type_):
        raise HTTPException(
            422, f"sourceDefinitionId is not supported for Moon building types ('{type_}'): "
                 "Moon buildings are not saved as building definitions"
        )


def _definition_row(conn: Connection, definition_id: UUID) -> dict:
    row = conn.execute("SELECT * FROM building_definition WHERE id = %s", (definition_id,)).fetchone()
    if row is None:
        raise HTTPException(422, f"building definition {definition_id} not found")
    return row


def snapshot_from_definition(row: dict) -> DefinitionSnapshot:
    return DefinitionSnapshot(
        name=row["name"], description=row["description"], template_id=row["template_id"],
        template_version=row["template_version"], stats=row["stats"], criteria=row["criteria"],
    )


def _dump(model) -> Jsonb:
    return Jsonb(model.model_dump(mode="json", by_alias=True))


def _json_or_none(v):
    return None if v is None else Jsonb(v)


def _remap_contributors(assumptions: dict, id_map: dict[str, str]) -> dict:
    """Point budget contributors at the branch's copies of the parent's projects."""
    budgets = assumptions.get("budgets")
    if not isinstance(budgets, list):
        return assumptions
    remapped = [
        {**b, "contributingProjectIds": [id_map.get(str(i), i) for i in b["contributingProjectIds"]]}
        if isinstance(b, dict) and isinstance(b.get("contributingProjectIds"), list) else b
        for b in budgets
    ]
    return {**assumptions, "budgets": remapped}


def _touch(conn: Connection, scenario_id: UUID) -> None:
    conn.execute("UPDATE scenario SET updated_at = now() WHERE id = %s", (scenario_id,))


def _place(latitude: float, longitude: float) -> tuple[float, float, str]:
    try:
        latitude, longitude = geo.validate_coordinate(latitude, longitude)
    except geo.InvalidCoordinate as exc:
        raise HTTPException(422, str(exc)) from exc
    return latitude, longitude, geo.simulation_cell(latitude, longitude)


# --- scenarios ---------------------------------------------------------------


@router.get("/scenarios", response_model=list[ScenarioSummary], response_model_by_alias=True)
def list_scenarios(body: WorldBody = Query("earth", description="Only worlds on this body (default Earth)")):
    with transaction() as conn:
        return conn.execute(
            """
            SELECT s.*, count(p.id)::int AS project_count
            FROM scenario s LEFT JOIN project p ON p.scenario_id = s.id
            WHERE s.body = %s
            GROUP BY s.id ORDER BY s.created_at
            """,
            (body,),
        ).fetchall()


@router.post("/scenarios", response_model=Scenario, status_code=201, response_model_by_alias=True)
def create_scenario(body: ScenarioCreate):
    with transaction() as conn:
        row = conn.execute(
            "INSERT INTO scenario (name, body, assumptions) VALUES (%s, %s, %s) RETURNING id",
            (body.name.strip(), body.body, Jsonb(validated_assumptions(body.assumptions))),
        ).fetchone()
        return _load_scenario(conn, row["id"])


@router.get("/scenarios/{scenario_id}", response_model=Scenario, response_model_by_alias=True)
def get_scenario(scenario_id: UUID):
    with transaction() as conn:
        return _load_scenario(conn, scenario_id)


@router.patch("/scenarios/{scenario_id}", response_model=Scenario, response_model_by_alias=True)
def update_scenario(scenario_id: UUID, body: ScenarioUpdate):
    """`assumptions` is merged key by key into the stored object (top level), so sending only
    `stress` keeps `budgets` and any legacy keys. Building-system keys are validated."""
    with transaction() as conn:
        current = conn.execute(
            "SELECT assumptions FROM scenario WHERE id = %s FOR UPDATE", (scenario_id,)
        ).fetchone()
        if current is None:
            raise HTTPException(404, "scenario not found")
        if body.name is not None:
            conn.execute("UPDATE scenario SET name = %s WHERE id = %s", (body.name.strip(), scenario_id))
        if body.assumptions is not None:
            stored_own, stored_other = _split_assumptions(current["assumptions"] or {})
            new_own, new_other = _split_assumptions(body.assumptions)
            merged = {**stored_other, **new_other}
            if new_own:
                merged.update(validated_assumptions({**stored_own, **new_own}))
            else:
                merged.update(stored_own)
            conn.execute("UPDATE scenario SET assumptions = %s WHERE id = %s", (Jsonb(merged), scenario_id))
        _touch(conn, scenario_id)
        return _load_scenario(conn, scenario_id)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: UUID):
    with transaction() as conn:
        if conn.execute("DELETE FROM scenario WHERE id = %s", (scenario_id,)).rowcount == 0:
            raise HTTPException(404, "scenario not found")
    return Response(status_code=204)


@router.post(
    "/scenarios/{scenario_id}/branch",
    response_model=Scenario,
    status_code=201,
    response_model_by_alias=True,
)
def branch_scenario(scenario_id: UUID, body: ScenarioBranch):
    """Copy a scenario and its projects; the branch keeps the same body, baseline and model versions.
    Definition snapshots, site assumptions and scenario assumptions (incl. stress controls) are
    copied by value, so later edits on either side are independent. Budget contributors are
    re-pointed at the copied projects, so the branch evaluates exactly like its parent."""
    with transaction() as conn:
        _load_scenario(conn, scenario_id)
        row = conn.execute(
            """
            INSERT INTO scenario (name, body, parent_scenario_id, baseline_revision, model_version, assumptions)
            SELECT %s, body, id, baseline_revision, model_version, assumptions FROM scenario WHERE id = %s
            RETURNING id, assumptions
            """,
            (body.name.strip(), scenario_id),
        ).fetchone()
        id_map: dict[str, str] = {}
        parent_projects = conn.execute(
            "SELECT id FROM project WHERE scenario_id = %s ORDER BY created_at, id", (scenario_id,)
        ).fetchall()
        for p in parent_projects:
            copy = conn.execute(
                """
                INSERT INTO project (scenario_id, type, name, latitude, longitude, h3_id, h3_resolution,
                                     parameters, definition, source_definition_id, site)
                SELECT %s, type, name, latitude, longitude, h3_id, h3_resolution,
                       parameters, definition, source_definition_id, site
                FROM project WHERE id = %s
                RETURNING id
                """,
                (row["id"], p["id"]),
            ).fetchone()
            id_map[str(p["id"])] = str(copy["id"])
        if row["assumptions"]:
            conn.execute(
                "UPDATE scenario SET assumptions = %s WHERE id = %s",
                (Jsonb(_remap_contributors(row["assumptions"], id_map)), row["id"]),
            )
        return _load_scenario(conn, row["id"])


# --- projects ----------------------------------------------------------------


@router.post(
    "/scenarios/{scenario_id}/projects",
    response_model=Project,
    status_code=201,
    response_model_by_alias=True,
)
def create_project(scenario_id: UUID, body: ProjectCreate):
    """Place a building. Without `definition` but with `sourceDefinitionId`, the saved definition is
    snapshotted (and its parameters used when none are given). No definition at all = legacy project.
    Moon types go in Moon worlds only, Earth types in Earth worlds only."""
    latitude, longitude, h3_id = _place(body.latitude, body.longitude)
    parameters, definition = body.parameters, body.definition
    with transaction() as conn:
        _check_world(_scenario_body(conn, scenario_id), body.type)
        if body.source_definition_id is not None:
            _no_definition_link(body.type)
            source = _definition_row(conn, body.source_definition_id)
            if definition is None:
                if body.type != source["type"]:
                    raise HTTPException(
                        422, f"type '{body.type}' does not match the building definition's type '{source['type']}'"
                    )
                definition = snapshot_from_definition(source)
                parameters = parameters or source["parameters"]
        _check_parameters(body.type, parameters)
        project = conn.execute(
            f"""
            INSERT INTO project (scenario_id, type, name, latitude, longitude, h3_id, h3_resolution, parameters,
                                 definition, source_definition_id, site)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {PROJECT_COLUMNS}
            """,
            (
                scenario_id,
                body.type,
                body.name.strip(),
                latitude,
                longitude,
                h3_id,
                geo.SIMULATION_RESOLUTION,
                Jsonb(parameters),
                _dump(definition) if definition is not None else None,
                body.source_definition_id,
                _dump(body.site or SiteAssumptions()),
            ),
        ).fetchone()
        _touch(conn, scenario_id)
        return project_out(project)


@router.patch("/projects/{project_id}", response_model=Project, response_model_by_alias=True)
def update_project(project_id: UUID, body: ProjectUpdate):
    with transaction() as conn:
        current = conn.execute(
            f"SELECT {PROJECT_COLUMNS} FROM project WHERE id = %s FOR UPDATE", (project_id,)
        ).fetchone()
        if current is None:
            raise HTTPException(404, "project not found")

        latitude = body.latitude if body.latitude is not None else current["latitude"]
        longitude = body.longitude if body.longitude is not None else current["longitude"]
        latitude, longitude, h3_id = _place(latitude, longitude)

        type_ = body.type or current["type"]
        if body.type is not None:
            _check_world(_scenario_body(conn, current["scenario_id"]), type_)
        parameters = body.parameters if body.parameters is not None else current["parameters"]
        if body.parameters is not None or body.type is not None:
            _check_parameters(type_, parameters)
        source_id = current["source_definition_id"]
        if "source_definition_id" in body.model_fields_set:
            source_id = body.source_definition_id
            if source_id is not None:
                _no_definition_link(type_)
                _definition_row(conn, source_id)

        project = conn.execute(
            f"""
            UPDATE project SET type = %s, name = %s, latitude = %s, longitude = %s, h3_id = %s,
                               parameters = %s, definition = %s, source_definition_id = %s, site = %s,
                               updated_at = now()
            WHERE id = %s
            RETURNING {PROJECT_COLUMNS}
            """,
            (
                type_,
                body.name.strip() if body.name is not None else current["name"],
                latitude,
                longitude,
                h3_id,
                Jsonb(parameters),
                _dump(body.definition) if body.definition is not None else _json_or_none(current["definition"]),
                source_id,
                _dump(body.site) if body.site is not None else Jsonb(current["site"]),
                project_id,
            ),
        ).fetchone()
        _touch(conn, current["scenario_id"])
        return project_out(project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: UUID):
    with transaction() as conn:
        row = conn.execute(
            "DELETE FROM project WHERE id = %s RETURNING scenario_id", (project_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "project not found")
        _touch(conn, row["scenario_id"])
    return Response(status_code=204)
