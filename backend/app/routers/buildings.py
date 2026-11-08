"""Building templates, saved definitions, placement assessment and scenario stress evaluation
(CLAUDE.Building-System.md sections 4, 7, 10 and 11). Assessments and evaluations are read-only."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from psycopg import Connection
from psycopg.types.json import Jsonb

from app import building_assess, building_presets, building_templates, geo
from app.building_assess import AreaTooLarge, PlacedBuilding, ScenarioContext
from app.building_calc import CalcInputError
from app.building_models import (
    AssessmentRequest,
    AssessmentResponse,
    BuildingDefinition,
    BuildingDefinitionInput,
    BuildingDefinitionPatch,
    BuildingPreset,
    BuildingTemplate,
    EvaluateRequest,
    ScenarioEvaluation,
    SiteAssumptions,
)
from app.db import transaction
from app.layers import REGION_BOXES
from app.routers.scenarios import PROJECT_COLUMNS, _check_parameters, scenario_assumptions, snapshot_of

router = APIRouter(prefix="/api", tags=["buildings"])


@router.get("/scenarios/{scenario_id}/timeline")
def get_timeline(scenario_id: UUID):
    from app.timeline import timeline_inputs

    with transaction() as conn:
        ctx = load_context(conn, scenario_id)
    try:
        return timeline_inputs(ctx)
    except (ValueError, CalcInputError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _jsonb(value) -> Jsonb:
    if hasattr(value, "model_dump"):
        return Jsonb(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, list):
        return Jsonb([v.model_dump(mode="json", by_alias=True) if hasattr(v, "model_dump") else v for v in value])
    return Jsonb(value)


# --- templates --------------------------------------------------------------------------------


@router.get("/building-templates", response_model=list[BuildingTemplate], response_model_by_alias=True)
def list_templates():
    """Predefined types as forms: fields, units and help text. No numeric defaults (none are cited)."""
    return building_templates.TEMPLATES


@router.get("/building-presets", response_model=list[BuildingPreset], response_model_by_alias=True)
def list_presets():
    """Real example buildings: every number is cited to a listed source; unknowns stay blank."""
    return list(building_presets.load_presets())


# --- definitions ------------------------------------------------------------------------------


def _definition_out(row: dict) -> BuildingDefinition:
    return BuildingDefinition.model_validate({
        **row,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    })


def _get_definition(conn: Connection, definition_id: UUID) -> dict:
    row = conn.execute("SELECT * FROM building_definition WHERE id = %s", (definition_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "building definition not found")
    return row


@router.get("/building-definitions", response_model=list[BuildingDefinition], response_model_by_alias=True)
def list_definitions():
    with transaction() as conn:
        rows = conn.execute("SELECT * FROM building_definition ORDER BY created_at, id").fetchall()
    return [_definition_out(r) for r in rows]


@router.post("/building-definitions", response_model=BuildingDefinition, status_code=201,
             response_model_by_alias=True)
def create_definition(body: BuildingDefinitionInput):
    _check_parameters(body.type, body.parameters)
    with transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO building_definition (name, description, type, template_id, template_version,
                                             stats, parameters, criteria)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
            """,
            (body.name.strip(), body.description, body.type, body.template_id, body.template_version,
             _jsonb(body.stats), _jsonb(body.parameters), _jsonb(body.criteria)),
        ).fetchone()
    return _definition_out(row)


@router.get("/building-definitions/{definition_id}", response_model=BuildingDefinition,
            response_model_by_alias=True)
def get_definition(definition_id: UUID):
    with transaction() as conn:
        return _definition_out(_get_definition(conn, definition_id))


@router.patch("/building-definitions/{definition_id}", response_model=BuildingDefinition,
              response_model_by_alias=True)
def update_definition(definition_id: UUID, body: BuildingDefinitionPatch):
    """Affects future placements only: placed buildings keep their own snapshot.

    `templateId` / `templateVersion` are written when sent. A type change without them clears both,
    so the definition never keeps the template of its previous type."""
    with transaction() as conn:
        current = _get_definition(conn, definition_id)
        type_ = body.type or current["type"]
        parameters = body.parameters if body.parameters is not None else current["parameters"]
        if body.type is not None or body.parameters is not None:
            _check_parameters(type_, parameters)
        sent = body.model_fields_set
        type_changed = type_ != current["type"]
        template_id, template_version = current["template_id"], current["template_version"]
        if "template_id" in sent:
            template_id = body.template_id
        elif type_changed:
            template_id = None
        if "template_version" in sent:
            template_version = body.template_version
        elif type_changed or template_id != current["template_id"]:
            template_version = None
        row = conn.execute(
            """
            UPDATE building_definition
            SET name = %s, description = %s, type = %s, template_id = %s, template_version = %s,
                stats = %s, parameters = %s, criteria = %s, updated_at = now()
            WHERE id = %s RETURNING *
            """,
            (
                body.name.strip() if body.name is not None else current["name"],
                body.description if body.description is not None else current["description"],
                type_,
                template_id,
                template_version,
                _jsonb(body.stats if body.stats is not None else current["stats"]),
                _jsonb(parameters),
                _jsonb(body.criteria if body.criteria is not None else current["criteria"]),
                definition_id,
            ),
        ).fetchone()
    return _definition_out(row)


@router.delete("/building-definitions/{definition_id}", status_code=204)
def delete_definition(definition_id: UUID):
    """Placed buildings keep their snapshots; their source link is cleared (ON DELETE SET NULL)."""
    with transaction() as conn:
        if conn.execute("DELETE FROM building_definition WHERE id = %s", (definition_id,)).rowcount == 0:
            raise HTTPException(404, "building definition not found")
    return Response(status_code=204)


# --- assessment and evaluation ----------------------------------------------------------------


def load_context(conn: Connection, scenario_id: UUID | None) -> ScenarioContext:
    if scenario_id is None:
        return ScenarioContext()
    row = conn.execute("SELECT assumptions, body FROM scenario WHERE id = %s", (scenario_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "scenario not found")
    if row["body"] != "earth":
        # Timeline, evaluation and assessments model Earth buildings, layers and resources only.
        raise HTTPException(
            422, f"scenario {scenario_id} is a Moon world: timeline, evaluation and building assessments "
                 "are only available for Earth worlds"
        )
    projects = conn.execute(
        f"SELECT {PROJECT_COLUMNS} FROM project WHERE scenario_id = %s ORDER BY created_at, id", (scenario_id,)
    ).fetchall()
    return ScenarioContext(
        assumptions=scenario_assumptions(row["assumptions"]),
        buildings=[
            PlacedBuilding(
                id=p["id"], name=p["name"] or p["type"], type=p["type"], latitude=p["latitude"],
                longitude=p["longitude"], h3_id=p["h3_id"], snapshot=snapshot_of(p),
                parameters=p["parameters"] or {}, site=SiteAssumptions.model_validate(p["site"] or {}),
            )
            for p in projects
        ],
    )


@router.post("/building-assessments", response_model=AssessmentResponse, response_model_by_alias=True)
def assess(body: AssessmentRequest):
    """Read-only: assess a draft definition at an exact location or over a bounded area (res-6 cells).

    Area mode applies only layer limits, definition-only checks and scenario budgets whose scope
    covers the cell; the request's `site` assumptions apply to an exact `location` only.
    """
    _check_parameters(body.type, body.parameters)
    with transaction() as conn:
        ctx = load_context(conn, body.scenario_id)
    exclude = {body.exclude_project_id} if body.exclude_project_id else set()
    try:
        if body.location is not None:
            loc = building_assess.assess_location(
                body.type, body.stats, body.parameters, body.criteria, body.site,
                body.location.latitude, geo.normalise_longitude(body.location.longitude), ctx, exclude,
            )
            return AssessmentResponse(period_days=ctx.period_days, location=loc)
        if body.region is not None:
            box = REGION_BOXES[body.region]
        else:
            b = body.bounds
            if not b.south < b.north:
                raise HTTPException(422, "bounds: south must be less than north")
            box = (b.west, b.south, b.east, b.north)
        area = building_assess.assess_area(body.type, body.stats, body.parameters, body.criteria, box, ctx,
                                           exclude, body.limit)
        return AssessmentResponse(period_days=ctx.period_days, area=area)
    except (AreaTooLarge, CalcInputError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/scenarios/{scenario_id}/evaluate", response_model=ScenarioEvaluation, response_model_by_alias=True)
def evaluate_scenario(scenario_id: UUID, body: EvaluateRequest | None = None):
    """Unstressed and stressed results for the same buildings, period and assumptions. `stress`,
    `periodDays` and `budgets` in the body preview unsaved controls; otherwise the scenario's saved
    values are used. Nothing is saved."""
    with transaction() as conn:
        ctx = load_context(conn, scenario_id)
    if body is not None:
        overrides = {k: v for k, v in (("period_days", body.period_days), ("budgets", body.budgets)) if v is not None}
        if overrides:
            ctx.assumptions = ctx.assumptions.model_copy(update=overrides)
    stress = body.stress if body is not None and body.stress is not None else ctx.assumptions.stress
    try:
        unstressed, stressed, notes = building_assess.evaluate(ctx, stress)
    except CalcInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    return ScenarioEvaluation(
        scenario_id=scenario_id,
        period_days=ctx.period_days,
        stress=stress,
        inputs_hash=building_assess.inputs_hash(ctx, stress),
        unstressed=unstressed,
        stressed=stressed,
        control_notes=notes,
    )
