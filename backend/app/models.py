from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ProjectType = Literal["data_centre", "solar", "greenhouse"]
ParamValue = float | int | str | bool


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LatLng(ApiModel):
    latitude: float
    longitude: float


class CellInfo(ApiModel):
    h3_id: str
    resolution: int
    is_pentagon: bool
    centre: LatLng
    boundary: list[list[float]] = Field(description="Closed ring of [longitude, latitude] pairs")
    area_km2: float
    neighbours: list[str]
    parent: str | None
    simulation_cell: str | None
    # No baseline layers are loaded yet; observations stay empty rather than invented.
    observations: list[dict] = []


class ProjectCreate(ApiModel):
    type: ProjectType
    name: str = ""
    latitude: float = Field(ge=-90, le=90)
    longitude: float
    parameters: dict[str, ParamValue] = {}


class ProjectUpdate(ApiModel):
    type: ProjectType | None = None
    name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = None
    parameters: dict[str, ParamValue] | None = None


class Project(ApiModel):
    id: UUID
    scenario_id: UUID
    type: ProjectType
    name: str
    latitude: float
    longitude: float
    h3_id: str
    h3_resolution: int
    parameters: dict[str, ParamValue]
    created_at: datetime
    updated_at: datetime


class ScenarioCreate(ApiModel):
    name: str = Field(min_length=1)
    assumptions: dict = {}


class ScenarioUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1)
    assumptions: dict | None = None


class ScenarioBranch(ApiModel):
    name: str = Field(min_length=1)


class ScenarioSummary(ApiModel):
    id: UUID
    name: str
    parent_scenario_id: UUID | None
    baseline_revision: str
    model_version: str
    project_count: int
    created_at: datetime
    updated_at: datetime


class Scenario(ApiModel):
    id: UUID
    name: str
    parent_scenario_id: UUID | None
    baseline_revision: str
    model_version: str
    assumptions: dict
    projects: list[Project]
    created_at: datetime
    updated_at: datetime
