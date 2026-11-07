"""Base pydantic model and scalar parameter type shared by app.models and app.building_models."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

ParamValue = float | int | str | bool


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
