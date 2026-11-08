"""Moon building catalogue (shared/moon_buildings.json) and parameter validation for Moon worlds.

Moon buildings are placed as projects in Moon worlds only (scenario.body = 'moon'). Their parameters
are numbers keyed by the catalogue's param keys; null (or absent) means unknown, never zero.
"""

import json
import math
from pathlib import Path

from app.building_calc import CalcInputError, fmt_num

CATALOGUE = json.loads((Path(__file__).resolve().parents[2] / "shared/moon_buildings.json").read_text())
BY_TYPE: dict[str, dict] = {b["type"]: b for b in CATALOGUE["buildings"]}
MOON_TYPES: tuple[str, ...] = tuple(BY_TYPE)
# Per type: param key -> spec ({key, unit, default, min, max, integer?, ...}).
PARAMS: dict[str, dict[str, dict]] = {t: {p["key"]: p for p in b["params"]} for t, b in BY_TYPE.items()}


def is_moon_type(btype: str) -> bool:
    return btype in BY_TYPE


def defaults(btype: str) -> dict[str, float | None]:
    """Catalogue defaults for one type; None = unknown."""
    return {key: spec["default"] for key, spec in PARAMS[btype].items()}


def _param_problem(key: str, spec: dict, v) -> str | None:
    if v is None:  # unknown
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return f"{key} must be a number or null"
    try:
        x = float(v)
    except OverflowError:  # an int too large for a float
        return f"{key} is out of range"
    if not math.isfinite(x):
        return f"{key} must be finite"
    if x < spec["min"]:
        return f"{key} must be at least {fmt_num(spec['min'])}"
    if x > spec["max"]:
        return f"{key} must be at most {fmt_num(spec['max'])}"
    if spec.get("integer") and not x.is_integer():
        return f"{key} must be a whole number"
    return None


def validate_parameters(btype: str, parameters: dict) -> None:
    """Reject invalid known parameters before saving: each must be absent, null or a finite number in
    [min, max] (whole when the catalogue says `integer`). Unknown extra keys are preserved as-is, but
    non-finite numbers are rejected anywhere."""
    if btype not in PARAMS:
        raise CalcInputError(f"'{btype}' is not a Moon building type")
    problems = []
    for key, spec in PARAMS[btype].items():
        err = _param_problem(key, spec, parameters.get(key))
        if err:
            problems.append(err)
    for key, v in parameters.items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"{key} must be finite")
    if problems:
        raise CalcInputError("; ".join(sorted(set(problems))))
