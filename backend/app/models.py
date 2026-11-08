import math
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field

from app.api_base import ApiModel, ParamValue
from app.building_models import BuildingType, DefinitionSnapshot, MoonBuildingType, SiteAssumptions

# Earth types (also used by saved definitions) followed by Moon types (Moon worlds only).
ProjectType = Literal[BuildingType, MoonBuildingType]
# The body a scenario (world) lives on; fixed at creation.
WorldBody = Literal["earth", "moon"]
# Project parameters: null = unknown (accepted for Moon types; Earth types reject it, omit the key instead).
ProjectParamValue = ParamValue | None

__all__ = ["ApiModel", "ParamValue"]  # re-exported for existing imports

NAME_MAX = 200


def _json_finite(value):
    """Reject NaN / infinity anywhere in free-form JSON: PostgreSQL jsonb cannot store them."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("numbers must be finite")
    if isinstance(value, dict):
        for v in value.values():
            _json_finite(v)
    elif isinstance(value, list):
        for v in value:
            _json_finite(v)
    return value


Assumptions = Annotated[dict, AfterValidator(_json_finite)]


class LatLng(ApiModel):
    latitude: float
    longitude: float


class CellInfo(ApiModel):
    h3_id: str
    resolution: int
    is_pentagon: bool
    centre: LatLng
    boundary: list[list[float]] = Field(description="Closed ring of [longitude, latitude] pairs")
    body: str = Field(description="Body whose radius sizes the cell: earth | moon")
    area_km2: float
    edge_length_km: float = Field(description="Average hexagon edge length at this resolution on the body")
    neighbours: list[str]
    parent: str | None
    simulation_cell: str | None
    # No baseline layers are loaded yet; observations stay empty rather than invented.
    observations: list[dict] = []


class ProjectCreate(ApiModel):
    type: ProjectType
    name: str = Field(default="", max_length=NAME_MAX)
    latitude: float = Field(ge=-90, le=90)
    longitude: float
    parameters: dict[str, ProjectParamValue] = {}
    # Building-system fields (CLAUDE.Building-System.md). Without `definition` but with
    # `source_definition_id`, the server snapshots that saved definition.
    definition: DefinitionSnapshot | None = None
    source_definition_id: UUID | None = None
    site: SiteAssumptions | None = None


class ProjectUpdate(ApiModel):
    type: ProjectType | None = None
    name: str | None = Field(default=None, max_length=NAME_MAX)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = None
    parameters: dict[str, ProjectParamValue] | None = None
    definition: DefinitionSnapshot | None = None
    source_definition_id: UUID | None = None  # explicit null clears the link
    site: SiteAssumptions | None = None


class Project(ApiModel):
    id: UUID
    scenario_id: UUID
    type: ProjectType
    name: str
    latitude: float
    longitude: float
    h3_id: str
    h3_resolution: int
    parameters: dict[str, ProjectParamValue]
    # Always present in responses: legacy rows are adapted (all new statistics unknown).
    definition: DefinitionSnapshot
    source_definition_id: UUID | None = None
    site: SiteAssumptions = SiteAssumptions()
    created_at: datetime
    updated_at: datetime


class ScenarioCreate(ApiModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    body: WorldBody = "earth"
    assumptions: Assumptions = {}


class ScenarioUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    assumptions: Assumptions | None = None


class ScenarioBranch(ApiModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)


class ScenarioSummary(ApiModel):
    id: UUID
    name: str
    body: WorldBody
    parent_scenario_id: UUID | None
    baseline_revision: str
    model_version: str
    project_count: int
    created_at: datetime
    updated_at: datetime


class Scenario(ApiModel):
    id: UUID
    name: str
    body: WorldBody
    parent_scenario_id: UUID | None
    baseline_revision: str
    model_version: str
    assumptions: dict
    projects: list[Project]
    created_at: datetime
    updated_at: datetime
