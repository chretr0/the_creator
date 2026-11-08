"""Graded site suitability (app/site_suitability.py): bands, the overall rule, profile selection and the
assessment API fields. Grades from prepared data skip when the data is not available."""

import math

import h3
import numpy as np
import pytest

from app import site_capacity as sc
from app import site_suitability as ss
from app.building_models import BuildingStats
from app.building_templates import TEMPLATES
from app.site_suitability import ANY, F, Profile, ge, le, rng

NAN = math.nan


def stats(**kw) -> BuildingStats:
    return BuildingStats.model_validate(kw)


RAW = object()  # compare unrounded values


def codes_of(values, spec, decimals=RAW):
    v = np.array(values, dtype=np.float64)
    if decimals is not RAW:
        v = ss._round_values(v, decimals)  # None = 3 significant figures
    return ss.classify(v, spec).tolist()


# --- band classification ----------------------------------------------------------------------


def test_two_sided_envelope_edges_are_inclusive():
    spec = F("soil_ph", 1, rng(6.0, 7.5), rng(5.5, 8.0), rng(5.0, 8.5))
    vals = [6.0, 7.5, 5.99, 7.51, 5.5, 8.0, 5.49, 8.01, 5.0, 8.5, 4.99, 8.51, NAN]
    assert codes_of(vals, spec) == [1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 0]


def test_one_sided_envelopes_and_open_marginal():
    n = F("soil_nitrogen", 1, ge(1.5), ge(1.0), ge(0.5))
    assert codes_of([1.5, 1.49, 1.0, 0.99, 0.5, 0.49, 20.0], n) == [1, 2, 2, 3, 3, 4, 1]
    share = F("farmland_share", 1, ge(50), ge(25), ANY)  # marginal = any: never unsuitable
    assert codes_of([50, 49, 25, 24, 0], share) == [1, 2, 2, 3, 3]
    rain = F("rainfall", 1, rng(200, 1600), le(2200), ANY)
    assert codes_of([199, 200, 1600, 1601, 2200, 2201, 5000], rain) == [2, 1, 1, 2, 2, 3, 3]


def test_values_are_graded_at_display_precision():
    slope = F("slope", 1, le(3), le(8), le(15), True)  # shown with 1 decimal
    assert codes_of([3.04, 3.06, 15.04, 15.06], slope, decimals=1) == [1, 2, 3, 4]
    people = F("market_access", 1, ge(1_000_000), ge(250_000), ANY)  # 3 significant figures
    assert codes_of([999_600, 249_400, 249_600], people, decimals=None) == [1, 3, 2]


def test_force_ideal_overrides_value_and_missing_data():
    spec = F("water_access", 1, ge(10), ge(1), ANY)
    out = ss.classify(np.array([0.0, NAN, 0.0]), spec, np.array([True, True, False]))
    assert out.tolist() == [1, 1, 3]


# --- overall rule -----------------------------------------------------------------------------


def run_overall(codes, weights, constraint=None):
    codes = np.array(codes, dtype=np.int8).reshape(len(weights), -1)
    constraint = constraint or [False] * len(weights)
    return ss.overall(codes, np.array(weights, dtype=float), np.array(constraint))


def tier(o, i=0):
    t = int(o.tier[i])
    return None if t == ss.NOT_GRADED else ss.TIERS[t]


def test_weighted_mean_cutoffs():
    # Two equal-weight good factors: score 2.0 exactly → good (no cap: worst is good).
    o = run_overall([[2], [2]], [1, 1])
    assert o.score[0] == 2.0 and tier(o) == "good"
    # ideal ×4 + good ×1 (weights 1) → (12 + 2) / 5 = 2.8 → ideal; ideal + good weights 1.5/1 → 2.6 → ideal
    assert tier(run_overall([[1], [1], [1], [1], [2]], [1] * 5)) == "ideal"
    o = run_overall([[1], [2]], [1.5, 1])
    assert o.score[0] == 2.6 and tier(o) == "ideal"
    o = run_overall([[1], [2]], [1, 1.5])
    assert o.score[0] == 2.4 and tier(o) == "good"
    # good + marginal (1 : 3) → 1.25 → marginal; good + unsuitable (5 : 3) → 1.25 → marginal
    o = run_overall([[2], [3]], [1, 3])
    assert o.score[0] == 1.25 and tier(o) == "marginal"
    o = run_overall([[3], [4]], [1, 1])
    assert o.score[0] == 0.5 and tier(o) == "unsuitable"


def test_missing_factors_are_excluded_and_low_coverage_is_not_graded():
    o = run_overall([[1], [0]], [1, 1])  # exactly half the weight has data → graded
    assert o.coverage[0] == 0.5 and o.score[0] == 3.0 and tier(o) == "ideal"
    o = run_overall([[1], [0]], [1, 1.01])
    assert o.coverage[0] < 0.5 and tier(o) is None and o.score[0] == 3.0
    o = run_overall([[0], [0]], [1, 1])
    assert tier(o) is None and math.isnan(o.score[0]) and o.coverage[0] == 0


def test_constraint_veto_beats_score_and_coverage():
    # constraint unsuitable → unsuitable even though the weighted mean would be good
    o = run_overall([[4], [1], [1], [1]], [1, 3, 3, 3], [True, False, False, False])
    assert o.score[0] == 2.7 and o.vetoed[0] and tier(o) == "unsuitable"
    # ... and even when coverage is too low to grade otherwise
    o = run_overall([[4], [0], [0]], [1, 5, 5], [True, False, False])
    assert tier(o) == "unsuitable"
    # a non-constraint unsuitable factor is not a veto
    assert not run_overall([[4], [1]], [1, 9]).vetoed[0]


def test_grade_is_capped_one_class_above_the_weakest_factor():
    # 17 ideal factors + one marginal: score 2.89 would be ideal, the marginal factor caps it at good
    o = run_overall([[1]] * 17 + [[3]], [1] * 18)
    assert o.score[0] == 2.89 and tier(o) == "good" and o.capped[0]
    # one non-constraint unsuitable factor among ideal ones: score 2.83, capped at marginal
    o = run_overall([[1]] * 17 + [[4]], [1] * 18)
    assert o.score[0] == 2.83 and tier(o) == "marginal" and o.capped[0] and not o.vetoed[0]
    # weakest factor good or ideal: no cap
    o = run_overall([[1]] * 17 + [[2]], [1] * 18)
    assert tier(o) == "ideal" and not o.capped[0]
    # the cap never raises a grade: score already marginal stays marginal
    o = run_overall([[3], [3], [2]], [1, 1, 1])
    assert tier(o) == "marginal" and not o.capped[0]
    # factors without data don't count as the weakest; ungraded cells stay ungraded
    assert tier(run_overall([[1], [0]], [1, 1])) == "ideal"
    assert tier(run_overall([[4], [0]], [1, 5])) is None


def test_constraint_factor_holds_the_grade_at_its_own_class():
    # the main resource (constraint, weight 3) is marginal, everything else ideal: score 2.5 gives good and
    # the one-class cap alone would allow good; the constraint holds it at marginal
    o = run_overall([[3]] + [[1]] * 9, [3] + [1] * 9, [True] + [False] * 9)
    assert tier(o) == "marginal" and o.held[0] and not o.vetoed[0]
    # a good constraint holds an otherwise ideal site at good
    o = run_overall([[2]] + [[1]] * 9, [1] * 10, [True] + [False] * 9)
    assert tier(o) == "good" and o.held[0] and not o.capped[0]
    # the same factor without the constraint flag only caps one class better: good
    o = run_overall([[3]] + [[1]] * 9, [3] + [1] * 9)
    assert tier(o) == "good" and not o.held[0]
    # a constraint without data holds nothing (but the no-data cap keeps it from ideal); it never raises a
    # lower grade
    o = run_overall([[0]] + [[1]] * 9, [1] * 10, [True] + [False] * 9)
    assert tier(o) == "good" and not o.held[0] and o.unconfirmed[0]
    o = run_overall([[1], [3], [3], [3]], [1, 1, 1, 1], [True, False, False, False])
    assert tier(o) == "marginal" and not o.held[0]


def fake_graded(profile: Profile, codes, values=None) -> ss.Graded:
    codes = np.array(codes, dtype=np.int8).reshape(len(profile.factors), -1)
    values = np.full(codes.shape, 1.0) if values is None else np.array(values, dtype=float).reshape(codes.shape)
    values[codes == 0] = np.nan
    res = ss.overall(codes, np.array([f.weight for f in profile.factors]),
                     np.array([f.constraint for f in profile.factors]))
    return ss.Graded(profile, None, values, codes, res)


TOY = Profile("toy", "Toy", "a toy", (
    F("soil_ph", 1, rng(6.0, 7.5), rng(5.5, 8.0), rng(5.0, 8.5)),
    F("slope", 1.5, le(3), le(8), le(15), True),
    F("rainfall", 2, rng(600, 1500), rng(400, 2000), rng(250, 3000)),
    F("temperature", 0.5, rng(6, 26), rng(3, 29), rng(0, 32)),
    F("farmland_share", 1, ge(50), ge(25), ANY),
))


def test_limiting_order_worst_first_then_weight():
    g = fake_graded(TOY, [[3], [1], [4], [4], [3]])
    s = g.at(0)
    # unsuitable before marginal; within a class heavier first; equal weights keep profile order
    assert s.limiting == ["rainfall", "temperature", "soil_ph", "farmland_share"]
    assert [f.key for f in s.factors] == [f.key for f in s.profile.factors]
    assert s.tier == "unsuitable" and s.summary.startswith("Unsuitable site for a toy: limited by annual rainfall")


def test_single_cell_summary_states_the_cap():
    g = fake_graded(TOY, [[1], [1], [1], [1], [3]], [[6.5], [1.0], [800], [10], [12]])
    s = g.at(0)
    assert s.tier == "good" and s.score == 2.67 and s.limiting == ["farmland_share"]  # 16 / 6: ideal by score
    assert s.summary.startswith("Good site for a toy: limited by existing farmland & grassland (marginal)")
    assert "caps the grade at good" in s.summary and "Graded on 5 of 5 factors." in s.summary
    farm = s.factors[4]
    assert farm.tier == "marginal" and farm.display == "12%" and farm.value == 12
    assert "outside the good band (≥ 25%)" in farm.explanation and "never unsuitable" in farm.explanation
    assert "at most one class better than the weakest factor" in s.profile.method


def test_veto_and_not_graded_summaries_and_no_data_factor():
    s = fake_graded(TOY, [[1], [4], [1], [1], [1]], [[6.5], [16.2], [800], [10], [60]]).at(0)
    assert s.tier == "unsuitable" and s.summary.startswith("Unsuitable for a toy: slope is unsuitable (16.2°)")
    assert "constraint" in s.factors[1].explanation
    s = fake_graded(TOY, [[1], [0], [0], [1], [0]]).at(0)
    assert s.tier is None and s.score == 3.0 and s.coverage == pytest.approx(1.5 / 6)
    assert s.summary.startswith("Not enough data") and "Graded on 2 of 5 factors." in s.summary
    assert s.factors[1].tier is None and s.factors[1].value is None and s.factors[1].display == "no data"


def test_cell_strings_counts_and_rank():
    g = fake_graded(TOY, [[1, 3, 0, 1], [1, 1, 0, 4], [1, 1, 0, 1], [1, 2, 0, 1], [1, 1, 0, 1]])
    assert g.grade_strings() == ["11111", "31121", "00000", "14111"]
    assert g.tier_names() == ["ideal", "good", None, "unsuitable"]
    assert g.tier_counts() == {"ideal": 1, "good": 1, "marginal": 0, "unsuitable": 1, "unknown": 1}
    assert g.rank.tolist() == [0, 1, 4, 3]


# --- text -------------------------------------------------------------------------------------


def bands(key, *envs, **kw):
    return ss.bands_text(F(key, 1, *envs, **kw))


def test_bands_text_is_generated_from_envelopes():
    assert bands("soil_ph", rng(6.0, 7.5), rng(5.5, 8.0), rng(5.0, 8.5)) == \
        "Ideal pH 6.0–7.5 · Good pH 5.5–8.0 · Marginal pH 5.0–8.5 · otherwise unsuitable"
    assert bands("soil_compaction", le(1.40), le(1.55), le(1.70)) == \
        "Ideal ≤ 1.40 kg/dm³ · Good ≤ 1.55 kg/dm³ · Marginal ≤ 1.70 kg/dm³ · otherwise unsuitable"
    assert bands("farmland_share", ge(50), ge(25), ANY) == "Ideal ≥ 50% · Good ≥ 25% · otherwise marginal"
    assert bands("rainfall", rng(600, 1500), rng(400, 2000), rng(250, 3000)).startswith("Ideal 600–1,500 mm/yr")
    assert bands("temperature", rng(5, 20), rng(0, 25), rng(-5, 30)).endswith("Marginal −5 to 30 °C · otherwise unsuitable")
    assert bands("market_access", ge(1_000_000), ge(250_000), ANY) == \
        "Ideal ≥ 1 million people · Good ≥ 250,000 people · otherwise marginal"
    assert bands("water_access", ge(10), ge(1), ge(0.1)) == \
        "Ideal ≥ 10 m³/s or coastal · Good ≥ 1 m³/s · Marginal ≥ 0.1 m³/s · otherwise unsuitable"
    assert bands("coastal", ge(1), ge(1), ge(1)) == "Ideal coastal · otherwise unsuitable"
    assert bands("wildfire", le(0), le(2), ANY) == "Ideal 0 detections · Good ≤ 2 detections · otherwise marginal"
    assert bands("groundwater", ge(40), ge(20), ANY) == \
        "Ideal ≥ 40th percentile · Good ≥ 20th percentile · otherwise marginal"
    assert bands("water_stress", le(1), le(2), le(4)).startswith("Ideal score ≤ 1 · Good score ≤ 2")


def test_value_display():
    d = lambda key, v: ss.display_value(ss.CATALOGUE[key], v)  # noqa: E731
    assert d("soil_nitrogen", 1.8) == "1.80 g/kg" and d("soil_ph", 6.4) == "pH 6.4"
    assert d("slope", 3.5) == "3.5°" and d("coldest_month", -3.2) == "−3.2 °C"
    assert d("market_access", 2_340_000) == "2.34 million people" and d("neighbours", 0.42) == "0.420 people/km²"
    assert d("groundwater", 62) == "62nd percentile" and d("growing_season", 1) == "1 month"
    assert d("coastal", 1.0) == "coastal" and d("coastal", 0.0) == "inland" and d("rainfall", None) == "no data"


# --- profiles ---------------------------------------------------------------------------------


def profile(btype, params=None, **st):
    return ss.profile_for(btype, stats(**st), params or {})


def spec_of(p, key):
    return next((f for f in p.factors if f.key == key), None)


def test_irrigated_vs_rainfed_selection():
    assert profile("farm", {"irrigation": "drip"}).id == "farm:irrigated"
    assert profile("farm", water={"inputM3PerHour": 5}).id == "farm:irrigated"  # no method: water input decides
    assert profile("farm").id == "farm:rainfed"
    assert profile("farm", water={"inputM3PerHour": 0}).id == "farm:rainfed"
    # explicit rain-fed wins even when water is declared (washing, spraying, stock)
    assert profile("farm", {"irrigation": "rainfed"}, water={"inputM3PerHour": 5}).id == "farm:rainfed"
    irr, rain = profile("farm", {"irrigation": "centre_pivot"}), profile("farm", {"irrigation": "rainfed"})
    assert spec_of(irr, "rainfall").weight == 0.5 and spec_of(irr, "rainfall").marginal == ANY
    assert spec_of(rain, "rainfall").weight == 2 and spec_of(rain, "rainfall").ideal == (600, 1500)
    assert {"river_flow", "groundwater"} <= {f.key for f in irr.factors} and spec_of(irr, "soil_moisture") is None
    # river only: a farm can't irrigate with seawater, so the coast never counts as water access
    assert spec_of(irr, "water_access") is None
    river = spec_of(irr, "river_flow")
    assert river.weight == 1 and (river.ideal, river.good, river.marginal) == (ge(10), ge(1), ANY)
    assert spec_of(rain, "soil_moisture") is not None and spec_of(rain, "river_flow") is None
    assert spec_of(irr, "water_stress").weight == 1.5 and spec_of(rain, "water_stress").weight == 0.5


def test_crop_overrides():
    cotton = profile("farm", {"cropType": "cotton", "irrigation": "drip"})
    assert cotton.id == "farm:irrigated:cotton" and cotton.label == "Crop farm · irrigated cotton"
    assert spec_of(cotton, "temperature").ideal == (15, 28) and spec_of(cotton, "growing_season").ideal == (8, None)
    warm = spec_of(cotton, "warmest_month")
    assert warm.constraint and warm.ideal == (24, 32) and warm.marginal == (18, 38)
    wheat = profile("farm", {"cropType": "wheat", "irrigation": "rainfed"})
    assert wheat.id == "farm:rainfed:wheat" and spec_of(wheat, "temperature").ideal == (6, 20)
    assert spec_of(wheat, "warmest_month").ideal == (None, 26) and not spec_of(wheat, "warmest_month").constraint
    vine_rain = profile("farm", {"cropType": "vineyard", "irrigation": "rainfed"})
    vine_irr = profile("farm", {"cropType": "vineyard", "irrigation": "drip"})
    for p in (vine_rain, vine_irr):
        assert spec_of(p, "slope").marginal == (None, 25) and spec_of(p, "slope").constraint
        assert spec_of(p, "soil_nitrogen").weight == 0.5
    assert spec_of(vine_rain, "rainfall").ideal == (500, 1000)
    assert spec_of(vine_irr, "rainfall").ideal == (200, 1600)  # rain-fed override doesn't touch irrigated
    rice = profile("farm", {"cropType": "rice", "irrigation": "rainfed"})
    assert spec_of(rice, "rainfall").ideal == (1200, 2500) and spec_of(rice, "soil_clay").ideal == (30, 60)
    # crops without an override keep the generic bands and id
    assert profile("farm", {"cropType": "vegetables", "irrigation": "drip"}).id == "farm:irrigated"


def test_conditional_factors():
    assert spec_of(profile("aquaculture"), "water_stress") is not None
    assert spec_of(profile("aquaculture", water={"source": "seawater"}), "water_stress") is None
    sea = profile("water_plant", water={"source": "seawater"})
    assert spec_of(sea, "coastal").constraint and spec_of(sea, "water_access") is None
    assert spec_of(profile("water_plant"), "water_access") is not None
    assert spec_of(profile("aluminium_smelter"), "electricity_price").weight == 2
    assert spec_of(profile("factory"), "electricity_price").weight == 1
    assert spec_of(profile("factory"), "water_stress").weight == 0.5
    assert spec_of(profile("factory", water={"inputM3PerHour": 3}), "water_stress").weight == 1
    assert spec_of(profile("factory"), "neighbours") is None and spec_of(profile("steel_mill"), "neighbours") is not None
    assert spec_of(profile("semiconductor_fab"), "market_access").ideal == (2_000_000, None)
    assert spec_of(profile("retail"), "market_access").marginal == (20_000, None)
    assert spec_of(profile("office"), "market_access").marginal == ANY
    assert spec_of(profile("solar"), "open_water").constraint and spec_of(profile("solar"), "open_water").weight == 0


def test_types_without_profile():
    for t in ("custom", "mine", "quarry", "oil_gas_field", "geothermal_plant", "battery_storage"):
        assert ss.profile_for(t, BuildingStats(), {}) is None
        assert ss.grade_for(t, BuildingStats(), {}, None) is None


def all_profiles():
    out = []
    for t in TEMPLATES:
        variants = [({}, {})]
        if t.type == "farm":
            variants = [({"cropType": c, "irrigation": m}, {}) for c in list(ss.CROP_OVERRIDES) + ["other"]
                        for m in ("rainfed", "drip")]
        if t.type in ("water_plant", "wastewater_plant", "aquaculture"):
            variants += [({}, {"water": {"source": "seawater"}})]
        for params, st in variants:
            p = ss.profile_for(t.type, stats(**st), params)
            if p is not None:
                out.append(p)
    return out


def test_every_profile_is_well_formed():
    profiles = all_profiles()
    assert len(profiles) > 40
    for p in profiles:
        assert len({f.key for f in p.factors}) == len(p.factors), p.id
        assert sum(f.weight for f in p.factors) > 0
        model = ss.profile_model(p)
        assert model.method == ss.METHOD and len(model.factors) == len(p.factors)
        for f in p.factors:
            fd = ss.CATALOGUE[f.key]
            assert fd.group in {"Soil", "Climate", "Terrain", "Land", "Water", "Energy", "People", "Air", "Hazards"}
            # nested envelopes: ideal ⊂ good ⊂ marginal
            for inner, outer in ((f.ideal, f.good), (f.good, f.marginal)):
                lo_ok = outer[0] is None or (inner[0] is not None and inner[0] >= outer[0])
                hi_ok = outer[1] is None or (inner[1] is not None and inner[1] <= outer[1])
                assert lo_ok and hi_ok, (p.id, f.key)


# --- prepared data ----------------------------------------------------------------------------


def test_constraint_without_data_caps_at_good():
    # every factor with data ideal, but a constraint has no data: the site can't be confirmed ideal
    o = run_overall([[0], [1], [1]], [1, 1, 1], [True, False, False])
    assert o.score[0] == 3.0 and tier(o) == "good" and o.unconfirmed[0] and not o.held[0] and not o.capped[0]
    # a weight-0 constraint without data counts too (it is not in the coverage)
    o = run_overall([[0], [1]], [0, 1], [True, False])
    assert o.coverage[0] == 1 and tier(o) == "good" and o.unconfirmed[0]
    # it never raises a lower grade, and a non-constraint without data doesn't cap
    assert tier(run_overall([[0], [2], [3]], [1, 1, 1], [True, False, False])) == "marginal"
    assert tier(run_overall([[0], [1], [1]], [1, 1, 1])) == "ideal"


def test_summary_explains_a_holding_constraint_in_both_branches():
    # no marginal factor at all: a good constraint (built-up land) holds an ideal score at good
    prof = Profile("toy2", "Toy", "a toy", (F("built_share", 1, le(5), le(15), le(40), True),
                                             F("rainfall", 3, rng(600, 1500), rng(400, 2000), ANY)))
    s = fake_graded(prof, [[2], [1]], [[8.0], [800]]).at(0)
    assert s.tier == "good" and s.score == 2.75 and s.limiting == []
    assert s.summary == ("Good site for a toy: every factor with data is ideal or good; built-up land (good) is a "
                         "constraint, so the site can't grade better than good (score 2.75). Graded on 2 of 2 factors.")
    # with a limiting (marginal) factor as well: the reason follows the limiting list
    s = fake_graded(TOY, [[1], [3], [1], [1], [1]], [[6.5], [10.0], [800], [10], [60]]).at(0)
    assert s.tier == "marginal" and s.limiting == ["slope"]
    assert s.summary.startswith("Marginal site for a toy: limited by slope (marginal); slope (marginal) is a "
                                "constraint, so the site can't grade better than marginal (score ")


def test_summary_explains_the_no_data_cap():
    s = fake_graded(TOY, [[1], [0], [1], [1], [1]], [[6.5], [0], [800], [10], [60]]).at(0)
    assert s.tier == "good" and s.score == 3.0 and s.limiting == []
    assert ("every factor with data is ideal or good; slope has no data here and is a constraint, so the site "
            "can't be confirmed better than good (score 3.00)") in s.summary
    assert "keeps the grade from ideal" in s.factors[1].explanation
    assert "at most good: the site can't be confirmed ideal" in s.profile.method


def test_silt_loam_is_prime_farmland():
    # McLean County, Illinois: silt loam with ~5% sand and ~34% clay is some of the best arable land there is
    farm = profile("farm", {"cropType": "maize", "irrigation": "rainfed"})
    assert codes_of([5.0], spec_of(farm, "soil_sand"), 1) == [1]
    assert codes_of([34.0], spec_of(farm, "soil_clay"), 1) == [1]
    sand = spec_of(farm, "soil_sand")
    assert (sand.ideal, sand.good, sand.marginal) == (le(60), le(70), le(85))
    potato = spec_of(profile("farm", {"cropType": "potatoes"}), "soil_sand")
    assert (potato.ideal, potato.good, potato.marginal) == (rng(30, 70), le(80), le(90))
    assert codes_of([5.0, 75, 85, 95], potato, 1) == [2, 2, 3, 4]


def test_maize_and_soybean_have_continental_bands():
    bands_of = lambda f: (f.ideal, f.good, f.marginal)  # noqa: E731
    maize = profile("farm", {"cropType": "maize", "irrigation": "rainfed"})
    soy = profile("farm", {"cropType": "soybean", "irrigation": "rainfed"})
    for p in (maize, soy):
        assert spec_of(p, "temperature").ideal == (8, 24) and spec_of(p, "growing_season").marginal == ge(4)
        assert codes_of([9.6], spec_of(p, "temperature"), 1) == [1]  # Iowa's 9.6 °C annual mean is ideal
        assert spec_of(p, "warmest_month").constraint
    # maize: UK silage (17.8 °C) is good, the hot Arizona valleys (34 °C, irrigated silage corn) are good
    warm = spec_of(maize, "warmest_month")
    assert bands_of(warm) == (rng(20, 32), rng(17, 35), rng(15, 38))
    assert codes_of([24.2, 17.8, 34.0, 14.9], warm, 1) == [1, 2, 2, 4]
    # soybean needs a warmer summer: the same English summer is only marginal
    warm = spec_of(soy, "warmest_month")
    assert bands_of(warm) == (rng(22, 30), rng(19, 33), rng(17, 36))
    assert codes_of([24.2, 17.8, 16.9], warm, 1) == [1, 3, 4]
    cotton = spec_of(profile("farm", {"cropType": "cotton"}), "warmest_month")
    assert cotton.ideal == (24, 32) and cotton.marginal == (18, 38)  # cotton and sugarcane keep the hot bands


def test_crop_farm_vetoes_dense_settlement():
    for params in ({}, {"irrigation": "drip"}, {"cropType": "wheat"}):
        homes = spec_of(profile("farm", params), "neighbours")
        assert homes.constraint and homes.weight == 0
        assert (homes.ideal, homes.good, homes.marginal) == (le(4000), le(4000), le(4000))  # a pure veto
        assert homes.why == "Dense settlement leaves no room for fields."
    assert codes_of([2000, 4000, 4010], homes, None) == [1, 1, 4]
    assert ss.bands_text(homes) == "Ideal ≤ 4,000 people/km² · otherwise unsuitable"


def test_dense_farmland_keeps_its_score_based_grade():
    # ~2,000 people/km² (Nile delta, Bangladesh, Bihar) with every other factor ideal: still ideal, not held
    p = profile("farm", {"cropType": "wheat", "irrigation": "drip"})
    codes = [[int(ss.classify(np.array([2000.0]), f)[0])] if f.key == "neighbours" else [1] for f in p.factors]
    o = fake_graded(p, codes).result
    assert tier(o) == "ideal" and not o.held[0] and not o.capped[0]
    # one good factor elsewhere: the score decides, the neighbours veto doesn't hold anything down
    codes[[f.key for f in p.factors].index("soil_ph")] = [2]
    assert tier(fake_graded(p, codes).result) == "ideal"


def test_wind_farm_siting():
    for params in ({}, {"siting": "onshore"}):
        on = profile("wind_farm", params)
        assert on.id == "wind_farm" and spec_of(on, "open_water") == ss.OPEN_WATER
        assert {"slope", "tree_cover", "built_share"} <= {f.key for f in on.factors}
    off = profile("wind_farm", {"siting": "offshore"})
    assert off.id == "wind_farm:offshore" and off.label == "Wind farm · offshore"
    assert not {"slope", "tree_cover", "built_share"} & {f.key for f in off.factors}
    assert spec_of(off, "open_water") is None
    sea = spec_of(off, "offshore_water")
    assert sea.constraint and sea.weight == 0 and (sea.ideal, sea.good, sea.marginal) == (ge(90), ge(75), ge(50))
    assert codes_of([100, 80, 60, 10], sea, 0) == [1, 2, 3, 4]
    assert ss.bands_text(sea) == "Ideal ≥ 90% · Good ≥ 75% · Marginal ≥ 50% · otherwise unsuitable"


def test_aquaculture_systems():
    pens = profile("aquaculture", {"system": "marine_net_pen"})
    assert pens.id == "aquaculture:marine_net_pen" and spec_of(pens, "coastal").constraint
    assert spec_of(pens, "water_stress") is None and spec_of(pens, "open_water") is None
    assert spec_of(profile("aquaculture", {"system": "shellfish_longline"}), "chlorophyll").weight == 1.5
    for system in ("freshwater_pond", "flow_through"):
        p = profile("aquaculture", {"system": system})
        assert spec_of(p, "river_flow") is not None and spec_of(p, "coastal") is None
        assert spec_of(p, "water_access") is None and spec_of(p, "open_water") is not None
    assert spec_of(profile("aquaculture", {"system": "flow_through"}), "river_flow").constraint
    ras = profile("aquaculture", {"system": "recirculating_ras"})
    assert spec_of(ras, "electricity_price").weight == 1.5 and spec_of(ras, "river_flow") is None
    assert profile("aquaculture").id == "aquaculture" and spec_of(profile("aquaculture"), "water_access").constraint


def test_wildfire_counts_vegetation_fires_only():
    fd = ss.CATALOGUE["wildfire"]
    assert (fd.layer_id, fd.slice_id) == ("fires_2024", "vegetation") and "vegetation" in fd.source
    from app import layers
    s = layers.BY_ID["fires_2024"].slice("vegetation")
    assert s.column == "type0_vegetation_fire" and s.label == "Vegetation fires"


needs_data = pytest.mark.skipif(
    sc._layer_src("soil_phh2o", "0-5cm") is None or sc._layer_src("land_cover", "crop") is None
    or sc._layer_src("air_temperature", "clim-ann") is None,
    reason="prepared SoilGrids / WorldCover / POWER data not available",
)


def site(points):
    lats = np.array([p[0] for p in points], dtype=float)
    lons = np.array([p[1] for p in points], dtype=float)
    cells = np.array([int(h3.latlng_to_cell(a, b, 6), 16) for a, b in points], dtype=np.uint64)
    return sc.site_data(cells, lats, lons)


@needs_data
def test_real_grades_east_anglia_vs_desert_and_sea():
    sd = site([(52.4, 0.9), (32.95, -113.2), (54.5, 1.5)])  # Norfolk arable, Sonoran desert, North Sea
    wheat = ss.grade_for("farm", BuildingStats(), {"cropType": "wheat", "irrigation": "rainfed"}, sd)
    t = wheat.tier_names()
    assert t[0] in ("ideal", "good") and t[1] in ("marginal", "unsuitable") and t[2] == "unsuitable"
    s = wheat.at(2)
    assert s.limiting[0] == "open_water" and "open water is unsuitable (100%)" in s.summary
    cotton = ss.grade_for("farm", BuildingStats(), {"cropType": "cotton", "irrigation": "drip"}, sd)
    assert cotton.tier_names()[0] == "unsuitable"  # an English summer is too cool for cotton (constraint)
    solar = ss.grade_for("solar", BuildingStats(), {}, sd)
    assert solar.result.score[1] > solar.result.score[0]


@needs_data
def test_water_outside_the_regions_is_inferred_and_vetoed():
    # Gulf of California, Lake Victoria, Atlantic off Lisbon (no soil, no people); Paris centre has no
    # SoilGrids value either but is populated, so it must not read as water; Sahara and Iowa are land
    sd = site([(28.0, -112.0), (-1.0, 33.0), (38.5, -10.5), (48.857, 2.352), (23.0, 10.0), (42.0, -93.5)])
    solar = ss.grade_for("solar", BuildingStats(), {}, sd)
    k = [f.key for f in solar.profile.factors].index("open_water")
    assert solar.values[k].tolist()[:3] == [100.0, 100.0, 100.0]
    assert np.isnan(solar.values[k, 3:]).all()  # land outside the regions: open water unknown
    assert solar.tier_names()[:3] == ["unsuitable"] * 3
    s = solar.at(0)
    ow = s.factors[k]
    assert ow.display == "100%, inferred" and "open water is unsuitable (100%, inferred)" in s.summary
    assert "Inferred from missing land data" in ow.explanation
    # fires: blank land cells are 0 detections, blank water cells are no data
    w = [f.key for f in solar.profile.factors].index("wildfire")
    assert np.isnan(solar.values[w, :3]).all() and (solar.values[w, 4:] >= 0).all()
    # land outside the regions can't be confirmed ideal: open water (a constraint) has no data
    assert solar.tier_names()[4] != "ideal" and solar.result.unconfirmed[4]
    dc = ss.grade_for("data_centre", BuildingStats(), {}, sd)
    assert dc.tier_names()[2] == "unsuitable" and dc.tier_names()[3] != "unsuitable"


@needs_data
def test_review_spot_checks():
    pts = [(40.758, -73.985), (42.0, -93.5), (51.1, -1.3), (55.6, -1.7), (54.5, 1.5)]
    sd = site(pts)  # Manhattan, Iowa, Hampshire, Northumberland coast, North Sea
    farm = ss.grade_for("farm", BuildingStats(), {}, sd)
    assert farm.tier_names()[0] == "unsuitable"  # dense city: neighbours veto (built-up share is regional)
    assert "neighbours nearby is unsuitable" in farm.at(0).summary
    maize = ss.grade_for("farm", BuildingStats(), {"cropType": "maize", "irrigation": "rainfed"}, sd)
    assert maize.tier_names()[1] in ("ideal", "good") and maize.tier_names()[2] in ("good", "marginal")
    irrigated = ss.grade_for("farm", BuildingStats(), {"irrigation": "drip"}, sd).at(3)
    assert "water_access" not in [f.key for f in irrigated.factors]
    river = next(f for f in irrigated.factors if f.key == "river_flow")
    assert river.display != "coastal" and river.tier != "ideal"
    on = ss.grade_for("wind_farm", BuildingStats(), {"siting": "onshore"}, sd).tier_names()[4]
    off = ss.grade_for("wind_farm", BuildingStats(), {"siting": "offshore"}, sd).tier_names()[4]
    assert on == "unsuitable" and off == "ideal"
    assert ss.grade_for("wind_farm", BuildingStats(), {"siting": "offshore"}, sd).tier_names()[1] == "unsuitable"


@needs_data
def test_steelworks_heat_is_not_wildfire():
    sd = site([(51.57, -3.77)])  # Port Talbot: hundreds of static-source detections, a handful of vegetation fires
    g = ss.grade_for("solar", BuildingStats(), {}, sd)
    k = [f.key for f in g.profile.factors].index("wildfire")
    assert g.values[k, 0] < 50


@needs_data
def test_industrial_land_without_soil_or_residents_is_not_water():
    # Caofeidian steelworks and Tianjin Nangang (reclaimed land: no SoilGrids soil, no GHSL residents)
    # and Tuas, Singapore (no soil, residents or fires: four mapped power plants in the cell)
    cells = {"86318d29fffffff": ("steel_mill", "seaport"), "86318d28fffffff": ("warehouse",),
             "86318d48fffffff": ("factory",), "866520c1fffffff": ("factory", "warehouse")}
    pts = [h3.cell_to_latlng(c) for c in cells]
    sd = site(pts)
    for btype in {b for v in cells.values() for b in v}:
        g = ss.grade_for(btype, BuildingStats(), {}, sd)
        k = [f.key for f in g.profile.factors].index("open_water")
        for i, (cell, types) in enumerate(cells.items()):
            if btype in types:
                assert np.isnan(g.values[k, i]), (btype, cell)  # no data, not a veto
                assert not (g.result.vetoed[i] and g.codes[k, i] == ss.UNSUITABLE)
    steel = ss.grade_for("steel_mill", BuildingStats(), {}, sd).at(0)
    ow = next(f for f in steel.factors if f.key == "open_water")
    assert ow.tier is None and ow.display == "no data" and "open water" not in steel.summary.split(":")[0]


@needs_data
def test_ice_is_not_open_sea():
    # Greenland, Antarctica, Vatnajökull and Svalbard (ice caps with a month just above 0 °C), North Sea (mapped)
    sd = site([(72.0, -40.0), (-80.0, 0.0), (64.4, -16.8), (79.0, 20.0), (54.5, 1.5)])
    off = ss.grade_for("wind_farm", BuildingStats(), {"siting": "offshore"}, sd)
    k = [f.key for f in off.profile.factors].index("offshore_water")
    assert (off.values[k, :4] == 0).all() and off.values[k, 4] == 100
    assert off.tier_names()[:4] == ["unsuitable"] * 4 and off.tier_names()[4] == "ideal"
    ice = off.at(0).factors[k]
    assert ice.display == "0%, inferred ice" and "not open sea" in ice.explanation
    land = ss.grade_for("solar", BuildingStats(), {}, sd).at(0)  # the land veto still applies, called ice
    ow = next(f for f in land.factors if f.key == "open_water")
    assert land.tier == "unsuitable" and ow.display == "100%, inferred ice" and "on ice" in ow.explanation


@needs_data
def test_soybean_needs_a_warmer_summer_than_maize():
    sd = site([(51.1, -1.3)])  # Hampshire: warmest month ~17.8 °C
    maize = ss.grade_for("farm", BuildingStats(), {"cropType": "maize", "irrigation": "rainfed"}, sd).tier_names()[0]
    soy = ss.grade_for("farm", BuildingStats(), {"cropType": "soybean", "irrigation": "rainfed"}, sd).tier_names()[0]
    assert maize == "good" and soy in ("marginal", "unsuitable")


# --- API --------------------------------------------------------------------------------------

PHOENIX_BOX = {"west": -112.6, "south": 33.0, "east": -112.3, "north": 33.25}


def test_api_area_returns_suitability_fields(client):
    body = {"type": "farm", "stats": {"footprintM2": 100_000}, "parameters": {"cropType": "cotton", "irrigation": "drip"},
            "bounds": PHOENIX_BOX, "limit": 15}
    r = client.post("/api/building-assessments", json=body)
    assert r.status_code == 200, r.text
    area = r.json()["area"]
    prof = area["suitability"]
    assert prof["id"] == "farm:irrigated:cotton" and "method" in prof
    f0 = prof["factors"][0]
    assert set(f0) == {"key", "label", "group", "unit", "weight", "constraint", "bands", "layerId", "sliceId",
                       "source", "why"}
    assert set(area["tierCounts"]) == {"ideal", "good", "marginal", "unsuitable", "unknown"}
    assert sum(area["tierCounts"].values()) == area["cellCount"] == len(area["cells"])
    for c in area["cells"]:
        assert set(c) == {"h3Id", "state", "tier", "grades"} and len(c["grades"]) == len(prof["factors"])
    cand = area["candidates"][0]["suitability"]
    assert set(cand) == {"profile", "tier", "score", "coverage", "limiting", "summary", "factors"}
    assert set(cand["factors"][0]) == {"key", "tier", "value", "display", "explanation"}
    assert [g["key"] for g in cand["factors"]] == [f["key"] for f in prof["factors"]]
    state_rank = {"meets_criteria": 0, "insufficient_data": 1, "fails_criteria": 2}
    tier_rank = {"ideal": 0, "good": 1, "marginal": 2, "unsuitable": 3, None: 4}
    keys = [(state_rank[c["assessment"]["state"]], tier_rank[c["suitability"]["tier"]], c["h3Id"])
            for c in area["candidates"]]
    assert keys == sorted(keys)
    by_cell = {c["h3Id"]: c for c in area["cells"]}
    for c in area["candidates"]:
        g = by_cell[c["h3Id"]]
        assert g["tier"] == c["suitability"]["tier"]
        assert g["grades"] == "".join("0" if f["tier"] is None else str(ss.TIERS.index(f["tier"]) + 1)
                                      for f in c["suitability"]["factors"])


def test_api_location_returns_suitability_and_types_without_profile_return_none(client):
    loc = {"latitude": 33.1, "longitude": -112.45}
    r = client.post("/api/building-assessments", json={"type": "solar", "location": loc})
    assert r.status_code == 200, r.text
    s = r.json()["location"]["suitability"]
    assert s["profile"]["id"] == "solar" and len(s["factors"]) == len(s["profile"]["factors"])
    assert 0 <= s["coverage"] <= 1 and isinstance(s["summary"], str) and isinstance(s["limiting"], list)

    r = client.post("/api/building-assessments", json={"type": "custom", "location": loc})
    assert r.json()["location"]["suitability"] is None
    area = client.post("/api/building-assessments", json={"type": "custom", "bounds": PHOENIX_BOX, "limit": 3}).json()["area"]
    assert area["suitability"] is None and area["tierCounts"] is None
    assert all(c["tier"] is None and c["grades"] is None for c in area["cells"])
    assert all(c["suitability"] is None for c in area["candidates"])
