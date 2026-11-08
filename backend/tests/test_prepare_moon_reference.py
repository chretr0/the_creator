"""Provenance written by scripts/moon/prepare_moon_reference.py: release date, supplements, evidence types.

Only pure helpers are exercised, so pyshp (needed only to read the
shapefiles) is stubbed when it is not installed, and no download or data file is touched.
"""

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(os.environ.get("MOON_REF_SCRIPT")
              or Path(__file__).resolve().parents[2] / "scripts" / "moon" / "prepare_moon_reference.py")


@pytest.fixture(scope="module")
def prep():
    with pytest.MonkeyPatch.context() as mp:
        if importlib.util.find_spec("shapefile") is None:
            mp.setitem(sys.modules, "shapefile", types.ModuleType("shapefile"))
        spec = importlib.util.spec_from_file_location("prepare_moon_reference_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


FILES = {k: {"retrievedAt": "2026-11-08T02:31:13Z"} for k in ("MOON-SITE-01", "MOON-PLACE-01", "MOON-PLACE-02")}
LAUNCH_DATED = ["Luna 16", "Luna 17", "Luna 20", "Luna 21", "Luna 23", "Luna 24", "Surveyor 1"]


def stats(**sites):
    s = {"lrocRows": 71, "release": "2026-08-14", "supplements": ["Luna9", "Luna13"],
         "nssdcaSupplements": ["Luna 9", "Luna 13"], "catalogueSupplements": [], "launchDated": LAUNCH_DATED}
    s.update(sites)
    return {"sites": s, "places": {"originsLeftToParent": 0},
            "mare": {"polygonsIn": 1, "features": 1, "invalidRepaired": 0}}


def test_luna23_gets_the_nssdca_landing_date(prep):
    assert "1974-11-06" in prep.date_note("Luna 23", "1974-10-28")


def test_every_named_luna_landing_has_an_nssdca_landing_date(prep):
    # data/README.md: launch-dated Luna rows get a dateNote with the NSSDCA landing date.
    lunas = [m for m in prep.CATALOGUE_SOFT_LANDINGS_NAMED if m.startswith("Luna ")]
    assert lunas and all(m in prep.NSSDCA_LANDING_DATES for m in lunas)


def test_current_run_text_is_unchanged(prep):
    s = prep.sources_block(FILES, stats())
    site, sup = s["MOON-SITE-01"], s["MOON-SITE-01-SUPPLEMENT"]
    assert site["limitations"][0] == (
        "Only objects located in LROC NAC images are listed; Luna 9 and Luna 13 are added from NASA NSSDCA "
        "(MOON-SITE-01-SUPPLEMENT), while impact sites never seen from orbit (Luna 2, Ranger 4, SMART-1, "
        "Lunar Prospector, most LM ascent stages and spent stages) are not included.")
    assert site["notes"].startswith("71 LROC rows (release of 2026-08-14) plus 2 supplement rows.")
    assert sup["limitations"] == [
        "Reported landing positions (0.01° precision), not measured from orbit: the Luna 9 and Luna 13 "
        "landers have not been identified in LROC images, so their true positions may differ.",
        f"Added because {prep.CATALOGUE} §9 (MOON-SITE-01 gotcha 3) lists them as missing; every §9 soft landing "
        "with a coordinate was found in the LROC file, so no catalogue coordinate had to be added.",
    ]


def test_site_provenance_follows_what_the_run_found(prep):
    # A --refresh where LROC has re-issued the file, now lists Luna 9, and has lost Apollo 11.
    s = prep.sources_block(FILES, stats(lrocRows=80, release="2026-12-01",
                                        supplements=["apollo-11-catalogue", "Luna13"],
                                        nssdcaSupplements=["Luna 13"], catalogueSupplements=["Apollo 11"]))
    site, sup = s["MOON-SITE-01"], s["MOON-SITE-01-SUPPLEMENT"]
    assert site["notes"].startswith("80 LROC rows (release of 2026-12-01) plus 2 supplement rows.")
    text = json.dumps([site, sup], ensure_ascii=False)
    assert "2026-08-14" not in text
    assert "Luna 9" not in text
    assert "no catalogue coordinate had to be added" not in text
    assert any("Apollo 11" in x for x in sup["limitations"])
    assert any("Luna 13 lander has not been identified" in x for x in sup["limitations"])


def test_missing_release_date_is_not_invented(prep):
    s = prep.sources_block(FILES, stats(release=None))
    assert "2026-08-14" not in s["MOON-SITE-01"]["notes"] and "None" not in s["MOON-SITE-01"]["notes"]


def test_no_supplement_means_no_nssdca_claim(prep):
    s = prep.sources_block(FILES, stats(supplements=[], nssdcaSupplements=[]))
    assert "MOON-SITE-01-SUPPLEMENT" not in s
    assert "NSSDCA" not in s["MOON-SITE-01"]["limitations"][0]


def test_launch_date_limitation_lists_the_rows_found(prep):
    s = prep.sources_block(FILES, stats(launchDated=["Luna 24"]))
    date_lim = [x for x in s["MOON-SITE-01"]["limitations"] if x.startswith("DATE ")]
    assert date_lim == ["DATE is documented as the arrival date, but for Luna 24 it holds the launch date; "
                        "affected rows carry a dateNote."]
    s = prep.sources_block(FILES, stats(launchDated=[]))
    assert not [x for x in s["MOON-SITE-01"]["limitations"] if x.startswith("DATE ")]


def test_reference_files_are_not_labelled_as_a_service(prep):
    s = prep.sources_block(FILES, stats())
    assert s["MOON-PLACE-01"]["evidenceType"] == "reference_gazetteer"
    assert s["MOON-PLACE-02"]["evidenceType"] == "reference_geometry"
