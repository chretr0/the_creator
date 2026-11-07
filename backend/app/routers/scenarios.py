from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from psycopg import Connection
from psycopg.types.json import Jsonb

from app import geo
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
)

router = APIRouter(prefix="/api", tags=["scenarios"])

PROJECT_COLUMNS = (
    "id, scenario_id, type, name, latitude, longitude, h3_id, h3_resolution, "
    "parameters, created_at, updated_at"
)


def _load_scenario(conn: Connection, scenario_id: UUID) -> dict:
    scenario = conn.execute("SELECT * FROM scenario WHERE id = %s", (scenario_id,)).fetchone()
    if scenario is None:
        raise HTTPException(404, "scenario not found")
    scenario["projects"] = conn.execute(
        f"SELECT {PROJECT_COLUMNS} FROM project WHERE scenario_id = %s ORDER BY created_at, id",
        (scenario_id,),
    ).fetchall()
    return scenario


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
def list_scenarios():
    with transaction() as conn:
        return conn.execute(
            """
            SELECT s.*, count(p.id)::int AS project_count
            FROM scenario s LEFT JOIN project p ON p.scenario_id = s.id
            GROUP BY s.id ORDER BY s.created_at
            """
        ).fetchall()


@router.post("/scenarios", response_model=Scenario, status_code=201, response_model_by_alias=True)
def create_scenario(body: ScenarioCreate):
    with transaction() as conn:
        row = conn.execute(
            "INSERT INTO scenario (name, assumptions) VALUES (%s, %s) RETURNING id",
            (body.name.strip(), Jsonb(body.assumptions)),
        ).fetchone()
        return _load_scenario(conn, row["id"])


@router.get("/scenarios/{scenario_id}", response_model=Scenario, response_model_by_alias=True)
def get_scenario(scenario_id: UUID):
    with transaction() as conn:
        return _load_scenario(conn, scenario_id)


@router.patch("/scenarios/{scenario_id}", response_model=Scenario, response_model_by_alias=True)
def update_scenario(scenario_id: UUID, body: ScenarioUpdate):
    with transaction() as conn:
        _load_scenario(conn, scenario_id)
        if body.name is not None:
            conn.execute("UPDATE scenario SET name = %s WHERE id = %s", (body.name.strip(), scenario_id))
        if body.assumptions is not None:
            conn.execute(
                "UPDATE scenario SET assumptions = %s WHERE id = %s",
                (Jsonb(body.assumptions), scenario_id),
            )
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
    """Copy a scenario and its projects; the branch keeps the same baseline and model versions."""
    with transaction() as conn:
        _load_scenario(conn, scenario_id)
        row = conn.execute(
            """
            INSERT INTO scenario (name, parent_scenario_id, baseline_revision, model_version, assumptions)
            SELECT %s, id, baseline_revision, model_version, assumptions FROM scenario WHERE id = %s
            RETURNING id
            """,
            (body.name.strip(), scenario_id),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO project (scenario_id, type, name, latitude, longitude, h3_id, h3_resolution, parameters)
            SELECT %s, type, name, latitude, longitude, h3_id, h3_resolution, parameters
            FROM project WHERE scenario_id = %s ORDER BY created_at, id
            """,
            (row["id"], scenario_id),
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
    latitude, longitude, h3_id = _place(body.latitude, body.longitude)
    with transaction() as conn:
        _load_scenario(conn, scenario_id)
        project = conn.execute(
            f"""
            INSERT INTO project (scenario_id, type, name, latitude, longitude, h3_id, h3_resolution, parameters)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                Jsonb(body.parameters),
            ),
        ).fetchone()
        _touch(conn, scenario_id)
        return project


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

        project = conn.execute(
            f"""
            UPDATE project SET type = %s, name = %s, latitude = %s, longitude = %s, h3_id = %s,
                               parameters = %s, updated_at = now()
            WHERE id = %s
            RETURNING {PROJECT_COLUMNS}
            """,
            (
                body.type or current["type"],
                body.name.strip() if body.name is not None else current["name"],
                latitude,
                longitude,
                h3_id,
                Jsonb(body.parameters if body.parameters is not None else current["parameters"]),
                project_id,
            ),
        ).fetchone()
        _touch(conn, current["scenario_id"])
        return project


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
