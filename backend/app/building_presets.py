"""Real example buildings with cited figures (CLAUDE.Building-System.md, presets).

The presets live in ``app/presets/building_presets.json``: one object per real facility, every number
traced to a source listed with it. They are read and validated once, on first use, and served as-is
by ``GET /api/building-presets``. Dropping a preset on the map places a new hypothetical building;
nothing here is stored in the database.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter

from app.building_models import BuildingPreset

PRESETS_PATH = Path(__file__).parent / "presets" / "building_presets.json"

_ADAPTER = TypeAdapter(list[BuildingPreset])


@lru_cache(maxsize=1)
def load_presets() -> tuple[BuildingPreset, ...]:
    """Validated presets in file order. Raises on invalid data or duplicate ids (a packaging bug)."""
    presets = _ADAPTER.validate_python(json.loads(PRESETS_PATH.read_text(encoding="utf-8")))
    ids = [p.id for p in presets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate building preset ids: {', '.join(duplicates)}")
    return tuple(presets)
