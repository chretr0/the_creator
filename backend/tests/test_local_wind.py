import json

import numpy as np
import pytest

from app import local_wind
from app.config import settings


def write_grid(directory, u, v, speed):
    """A 3 x 4 synthetic grid: lat -1..1 (step 1), lon -180..90 (step 90)."""
    meta = {"grid": {"lat0": -1.0, "dlat": 1.0, "nlat": 3, "lon0": -180.0, "dlon": 90.0, "nlon": 4}}
    shape = (3, 4)
    np.savez_compressed(directory / local_wind.FILE, meta=np.array(json.dumps(meta)),
                        u10m=np.full(shape, u * 100, np.int16), v10m=np.full(shape, v * 100, np.int16),
                        ws10m=np.full(shape, speed * 100, np.int16))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "prepared_data_dir", str(tmp_path))
    local_wind._grid.cache_clear()
    yield tmp_path
    local_wind._grid.cache_clear()


@pytest.mark.parametrize(("u", "v", "expected"), [(3, 0, 270), (-3, 0, 90), (0, 3, 180), (0, -3, 0), (2, 2, 225)])
def test_direction_is_where_the_wind_blows_from(u, v, expected):
    assert local_wind.direction_from(u, v) == pytest.approx(expected)


def test_vector_mean_drift_and_mean_speed_are_reported_separately(prepared):
    write_grid(prepared, u=3, v=4, speed=7.5)
    wind = local_wind.local_wind(0.2, 10)
    assert wind["u"] == 3 and wind["v"] == 4
    assert wind["speed"] == 5  # net drift of the vector mean
    assert wind["meanSpeed"] == 7.5  # scalar mean speed, never smaller than the drift
    assert wind["fromDegrees"] == pytest.approx(216.9, abs=.1)
    assert (wind["gridLatitude"], wind["gridLongitude"]) == (0.0, 0.0)


def test_lookup_wraps_longitude_and_clips_latitude(prepared):
    write_grid(prepared, u=1, v=0, speed=1)
    assert local_wind.local_wind(80, 179)["gridLongitude"] == -180.0
    assert local_wind.local_wind(80, 179)["gridLatitude"] == 1.0
    assert local_wind.local_wind(-80, -100)["gridLatitude"] == -1.0


def test_calm_has_no_direction(prepared):
    write_grid(prepared, u=0, v=0, speed=2)
    assert local_wind.local_wind(0, 0)["fromDegrees"] is None


def test_missing_grid_means_unknown_not_calm(prepared):
    assert local_wind.local_wind(0, 0) is None
