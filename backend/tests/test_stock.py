"""Stock lenses (stock.py, stockdesign.py): the generic library and its rules, paraxial data, the vectorised
first-order solver and Seidel sums against the engine, ZMX and CSV import, build and match on the process pool."""

import base64
import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore import workers
from opticore.api.main import app
from opticore.designspace import DesignSpaceJobs, DesignSpaceSpec, metrics
from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.paraxial import paraxial_data, seidel_coefficients
from opticore.project import Project
from opticore.stock import (
    GENERIC,
    StockError,
    StockLens,
    _part_from_filename,
    generic_achromat,
    generic_library,
    lens_from_zmx,
    lens_paraxial,
    lenses_from_csv,
    make_generic_library,
)
from opticore.stockdesign import (
    StockMatchSpec,
    StockSpec,
    build_system,
    combo_title,
    entry_table,
    enumerate_first_order,
    lens_pool,
    match_runner,
    plan_build,
    plan_match,
    prescreen_task,
    run_stock_candidate,
    seidel_sums,
    stock_runner,
)
from opticore.system import compile_system

client = TestClient(app, raise_server_exceptions=False)
LIB = MaterialLibrary()


@pytest.fixture
def pool(monkeypatch):
    workers.shutdown()
    monkeypatch.setenv("OPTICORE_WORKERS", "3")
    yield
    workers.shutdown()


def _by_part():
    return {l.part: l for l in generic_library()}


def _sag(r, h):
    if r is None:
        return 0.0
    return h * h / (r * (1.0 + math.sqrt(1.0 - (h / r) ** 2)))


# ---------------------------------------------------------------------------------------------- library
def test_generic_library_meets_its_rules():
    lenses = generic_library()
    assert len(lenses) > 600 and {l.kind for l in lenses} >= {"plano_convex", "biconvex", "best_form", "meniscus", "plano_concave", "biconcave", "achromat"}
    assert {m for l in lenses for m in l.materials} >= {"N-BK7", "FUSED_SILICA", "N-SF11", "CAF2", "N-BAF10", "N-SF6", "SF2", "N-SK16", "N-SF5"}
    for l in lenses:
        assert l.catalog == GENERIC and l.price is None
        f = l.focal_length
        assert lens_paraxial(l, LIB)["efl"] == pytest.approx(f, rel=1e-9), l.part
        D, h = l.diameter, l.diameter / 2
        assert all(r is None or abs(r) >= 0.55 * D - 1e-9 for r in l.radii), l.part
        if l.kind == "achromat":
            assert l.thicknesses[1] == pytest.approx(max(1.5, 0.1 * D))
            assert l.thicknesses[0] + _sag(l.radii[1], h) - _sag(l.radii[0], h) >= max(1.0, 0.05 * D) - 0.05, l.part
            assert 1.2 * D <= f <= 40 * D
        elif f > 0:
            assert l.thicknesses[0] + _sag(l.radii[1], h) - _sag(l.radii[0], h) == pytest.approx(max(1.0, 0.07 * D), abs=1e-9), l.part
            assert D <= f <= 40 * D
        else:
            assert l.thicknesses[0] == pytest.approx(max(1.5, 0.12 * D))
            assert D <= -f <= 40 * D


def test_generic_library_is_reproduced_by_its_generator():
    stored = _by_part()
    singlets = make_generic_library(achromats=False)
    assert len(singlets) == sum(1 for l in stored.values() if l.kind != "achromat")
    for l in singlets:
        assert l == stored[l.part]
    for crown, flint, f, D in (("N-BAF10", "N-SF6", 100.0, 25.4), ("N-BK7", "SF2", 500.0, 50.8)):
        a = generic_achromat(crown, flint, f, D, LIB)
        b = stored[a.part]
        assert a.radii == pytest.approx(b.radii, rel=1e-9) and a.thicknesses == pytest.approx(b.thicknesses, rel=1e-12)


def test_generic_achromats_do_not_depend_on_the_process_pool(monkeypatch):
    """The generator always runs in-process: the optimiser picks the process pool by the time of its first evaluation,
    and on the pool one radius of the 500 mm achromat ended 64 mm away."""
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "force")
    a = generic_achromat("N-BK7", "SF2", 500.0, 50.8, LIB)
    assert a.radii == pytest.approx(_by_part()[a.part].radii, rel=1e-9)


def test_stock_lens_paraxial_data_equal_the_traced_system():
    lib = _by_part()
    for part in ("G-PCX-BK7-100-25.4", "G-ACH-BAF10-SF6-100-25.4", "G-PCV-SF11--50-25.4", "G-PMN-BK7-200-50.8"):
        l = lib[part]
        for rev in (False, True):
            p = lens_paraxial(l, LIB, 0.5875618, rev)
            spec = StockSpec(focal_length=abs(p["efl"]), f_number=10, half_field_deg=0, wavelengths=[0.5875618], primary=0)
            s = build_system([l], [(0, rev)], [], max(p["bfd"], 1.0), spec, "x")
            pd = paraxial_data(compile_system(s), 0)
            assert pd.efl == pytest.approx(p["efl"], rel=1e-12) and pd.bfl == pytest.approx(p["bfd"], rel=1e-9, abs=1e-9)
        f, r = lens_paraxial(l, LIB), lens_paraxial(l, LIB, reversed_=True)
        assert r["efl"] == pytest.approx(f["efl"], rel=1e-12)
        assert r["front_principal"] == pytest.approx(-f["rear_principal"], abs=1e-9) and r["rear_principal"] == pytest.approx(-f["front_principal"], abs=1e-9)


# ---------------------------------------------------------------------------------------------- first order and third order
@pytest.mark.parametrize("conj", ["infinite", "finite"])
def test_first_order_solutions_and_seidel_sums_equal_the_engine(conj):
    if conj == "infinite":
        spec = StockSpec(focal_length=80, f_number=6, half_field_deg=2, lens_counts=[1, 2, 3], triples=20000)
    else:
        spec = StockSpec(conjugate="finite", object_distance=120, magnification=-0.5, object_na=0.04, object_height=3, lens_counts=[1, 2, 3], triples=20000)
    lenses = lens_pool(spec, [])
    E = entry_table(lenses, spec)
    found = enumerate_first_order(E, spec)
    rng = np.random.default_rng(3)
    checked = 0
    for g in found:
        if not len(g["entries"]):
            continue
        for r in rng.choice(len(g["entries"]), size=min(4, len(g["entries"])), replace=False):
            combo = [(int(E["lens"][e]), bool(E["rev"][e])) for e in g["entries"][r]]
            s = build_system(lenses, combo, list(g["gaps"][r]), float(g["d_img"][r]), spec, "x")
            cs = compile_system(s)
            pd = paraxial_data(cs, spec.primary)
            if conj == "infinite":
                assert pd.efl == pytest.approx(g["value"][r], rel=1e-9) and abs(pd.efl - 80) <= 0.8 + 1e-9
                assert pd.bfl == pytest.approx(g["d_img"][r], rel=1e-9)
            else:
                assert pd.paraxial_magnification == pytest.approx(g["value"][r], rel=1e-9) and abs(pd.paraxial_magnification + 0.5) <= 0.005 + 1e-9
                assert abs(pd.image_surface_defocus) < 1e-6
            S = seidel_sums(E, g["entries"][r : r + 1], g["gaps"][r : r + 1], spec)
            ref = seidel_coefficients(cs, spec.primary)["total"]
            for k, v in ref.items():
                assert S[k][0] == pytest.approx(v, rel=1e-9, abs=1e-12), (k, combo_title(lenses, combo))
            checked += 1
    assert checked >= 8


def test_two_lens_focal_length_follows_gullstrand():
    """f = f1 f2 / (f1 + f2 - e), e the distance from the first lens's rear principal plane to the second's front one."""
    lib = _by_part()
    a, b = lib["G-PCX-BK7-50-25.4"], lib["G-PCV-BK7--75-25.4"]
    pa, pb = lens_paraxial(a, LIB), lens_paraxial(b, LIB)
    for d in (2.0, 10.0, 30.0):
        spec = StockSpec(focal_length=100, f_number=8, half_field_deg=0, wavelengths=[0.5875618], primary=0)
        s = build_system([a, b], [(0, False), (1, False)], [d], 50.0, spec, "x")
        e = -pa["rear_principal"] + d + pb["front_principal"]
        f = pa["efl"] * pb["efl"] / (pa["efl"] + pb["efl"] - e)
        assert paraxial_data(compile_system(s), 0).efl == pytest.approx(f, rel=1e-12)


# ---------------------------------------------------------------------------------------------- import
ZMX = """VERS 140000
MODE SUI
NAME LA1131 test
UNIT MM X W X CM MR CPMM
ENPD 10
SURF 0
  TYPE STANDARD
  CURV 0.0
  DISZ INFINITY
SURF 1
  STOP
  TYPE STANDARD
  CURV 0.0193498452
  DISZ 5.3
  GLAS N-BK7 0 0 1.5168 64.17
  DIAM 11.43
  MEMA 12.7
SURF 2
  TYPE STANDARD
  CURV 0.0
  DISZ 96.7
  DIAM 11.43
  MEMA 12.7
SURF 3
  TYPE STANDARD
  CURV 0.0
  DISZ 0
"""


def test_zmx_and_csv_import():
    assert _part_from_filename("LA1131-A-Zemax(ZMX).zmx") == "LA1131-A"
    assert _part_from_filename("AC254-100-A.zmx") == "AC254-100-A"
    lens, custom, diags = lens_from_zmx(ZMX, "LA1131-A-Zemax(ZMX).zmx", "My vendor", "Vendor")
    assert lens.part == "LA1131-A" and lens.kind == "plano_convex" and custom == []
    assert lens.radii == pytest.approx([1 / 0.0193498452, None][:1] + [None]) if False else lens.radii[0] == pytest.approx(1 / 0.0193498452)
    assert lens.radii[1] is None and lens.thicknesses == [5.3] and lens.materials == ["N-BK7"]
    assert lens.diameter == pytest.approx(25.4) and lens.clear == pytest.approx(22.86)
    with pytest.raises(StockError):
        lens_from_zmx(ZMX.replace("GLAS N-BK7 0 0 1.5168 64.17", "GLAS NOPE-GLASS"), "x.zmx", "c")
    with pytest.raises(StockError):
        lens_from_zmx(ZMX.replace("SURF 2\n  TYPE STANDARD\n  CURV 0.0", "SURF 2\n  TYPE STANDARD\n  CURV 0.0\n  CONI -1"), "x.zmx", "c")
    csv = "part,vendor,diameter,price,r1,t1,glass1,r2,t2,glass2,r3\nP1,Acme,25.4,40,51.68,4,N-BK7,inf,,,\nA1,Acme,25.4,90,62.75,4,N-BAF10,-45.71,2.5,N-SF6,-128.23\nBAD,Acme,abc,1,10,1,N-BK7,inf,,,\n"
    lenses, d = lenses_from_csv(csv, "Acme stock")
    assert [l.part for l in lenses] == ["P1", "A1"] and lenses[1].kind == "achromat" and lenses[0].price == 40
    assert len(d) == 1 and d[0]["line"] == 4
    with pytest.raises(StockError):
        lenses_from_csv("part,diameter\nx,1\n", "c")
    r = client.post("/api/v1/stock/import/zmx", json={"files": [{"filename": "LA1131-A-Zemax(ZMX).zmx", "content_base64": base64.b64encode(ZMX.encode()).decode()}, {"filename": "bad.zmx", "content_base64": base64.b64encode(b"nonsense").decode()}], "catalog": "Mine"})
    j = r.json()
    assert r.status_code == 200 and len(j["lenses"]) == 1 and j["lenses"][0]["paraxial"]["efl"] > 0
    assert [f["ok"] for f in j["files"]] == [True, False]
    r = client.post("/api/v1/stock/import/csv", json={"content": csv, "catalog": "Acme"})
    assert r.status_code == 200 and len(r.json()["lenses"]) == 2 and r.json()["diagnostics"][0]["line"] == 4
    s = client.post("/api/v1/stock/surfaces", json={"lens": lenses[1].model_dump(mode="json"), "reversed": True, "gap_after": 7}).json()["surfaces"]
    assert [x["radius"] for x in s] == pytest.approx([128.23, 45.71, -62.75]) and s[-1]["thickness"] == 7 and s[0]["semi_diameter_mode"] == "fixed"


# ---------------------------------------------------------------------------------------------- build
def test_build_candidates_are_reproducible_and_their_metrics_equal_a_reevaluation():
    spec = StockSpec(focal_length=100, f_number=5, half_field_deg=2, lens_counts=[1, 2], prescreen=60, candidates=4)
    pool_a, items_a, _ = plan_build(spec, [])
    pool_b, items_b, _ = plan_build(spec, [])
    assert items_a == items_b
    sj = spec.model_dump(mode="json")
    lj = [l.model_dump(mode="json") for l in pool_a]
    scores = sorted(prescreen_task(items_a, sj, lj, []), key=lambda x: x[1])
    best = {**items_a[scores[0][0]], "index": 0, "defocus": scores[0][2]}
    a = run_stock_candidate(best, sj, lj, [])
    b = run_stock_candidate(best, sj, lj, [])
    assert a["status"] == "finished" and a["feasible"], a.get("violations")
    assert a["metrics"] == b["metrics"]
    system = OpticalSystem.model_validate(a["system"])
    m = metrics(system, [], DesignSpaceSpec(mtf_frequency=spec.mtf_frequency, tolerances=False, wavelengths=spec.wavelengths, primary=spec.primary))
    for k in ("rms_spot_um", "mtf", "length_mm", "efl_mm", "mass_g"):
        assert m[k] == pytest.approx(a["metrics"][k], rel=1e-12)
    assert abs(a["metrics"]["efl_mm"] - 100) <= 1.0 and a["metrics"]["parts"] == len(best["combo"])
    # every surface of the result is a stock lens surface with its clear aperture, or the object or image
    assert all(s.semi_diameter_mode == "fixed" and s.comment.startswith("Stock lens") for s in system.surfaces[1:-1])


def _wait(job, jobs, timeout=300.0):
    t0 = time.time()
    while job["state"] == "running":
        jobs.snapshot(job)  # keep the job watched
        assert time.time() - t0 < timeout
        time.sleep(0.2)


def test_one_to_one_relay_is_the_classic_pair_of_achromats(pool):
    """Magnification -1 with the object 96 mm before the first lens (about the front focal distance of the generic
    f = 100 mm achromats): the best design is two f = 100 mm achromats with their crowns facing each other."""
    spec = StockSpec(conjugate="finite", object_distance=96, magnification=-1, object_na=0.08, object_height=2, lens_counts=[2], prescreen=400, candidates=12)
    jobs = DesignSpaceJobs()
    job = jobs.start(spec, [], runner=stock_runner(jobs, spec, [], []))
    _wait(job, jobs)
    s = jobs.snapshot(job)
    assert s["state"] == "finished" and s["done"] == s["total"] == 12
    good = sorted((c for c in s["candidates"] if c["status"] == "finished" and c["feasible"]), key=lambda c: c["metrics"]["rms_spot_um"])
    best = good[0]
    first, second = best["title"].split(" + ")
    assert first.startswith("G-ACH-") and "-100-" in first and first.endswith("(rev.)")
    assert second.startswith("G-ACH-") and "-100-" in second and not second.endswith("(rev.)")
    assert abs(best["metrics"]["magnification"] + 1) <= 0.01


def test_build_job_through_the_api_opens_as_a_project(pool):
    body = {"spec": {"focal_length": 50, "f_number": 4, "half_field_deg": 1, "lens_counts": [1, 2], "prescreen": 120, "candidates": 6, "materials": ["N-BK7", "N-BAF10", "N-SF6"]}}
    r = client.post("/api/v1/stock/build/start", json=body)
    assert r.status_code == 200
    jid = r.json()["job_id"]
    t0 = time.time()
    while True:
        s = client.get(f"/api/v1/design-space/{jid}").json()
        if s["state"] != "running":
            break
        assert time.time() - t0 < 300
        time.sleep(0.3)
    assert s["state"] == "finished" and s["done"] == 6 and s["notes"] and s["objectives"] == ["rms_spot_um", "length_mm", "parts"]
    assert all(set(c["glasses"]) <= {"N-BK7", "N-BAF10", "N-SF6"} for c in s["candidates"])
    c = client.get(f"/api/v1/design-space/{jid}/candidates/{s['candidates'][0]['index']}").json()
    p = Project.model_validate(c["project"])
    assert "stock lenses" in p.metadata.description and p.optimization.variables
    r = client.post("/api/v1/stock/build/start", json={"spec": {"materials": ["NOTHING"]}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "STOCK_DESIGN"


# ---------------------------------------------------------------------------------------------- match
def test_match_finds_the_parts_a_design_was_made_of(pool):
    lib = _by_part()
    a, b = lib["G-PCX-BK7-50-25.4"], lib["G-PCV-FS--100-25.4"]
    spec0 = StockSpec(focal_length=100, f_number=8, half_field_deg=1, lens_counts=[2])
    original = build_system([a, b], [(0, False), (1, False)], [12.0], 80.0, spec0, "made of stock")
    # perturb the radii by 1 % (an optimised design near the stock parts)
    d = original.model_dump()
    for s in d["surfaces"][1:-1]:
        if s["radius"] is not None:
            s["radius"] *= 1.01
        s["semi_diameter_mode"] = "auto"
        s["comment"] = ""
    design = OpticalSystem.model_validate(d)
    spec = StockMatchSpec(per_element=3, candidates=6)
    _, items, stats = plan_match(spec, design, [])
    assert len(stats["elements"]) == 2 and len(items) == 9
    jobs = DesignSpaceJobs()
    job = jobs.start(spec, [], runner=match_runner(jobs, spec, design, None, [], []))
    _wait(job, jobs)
    s = jobs.snapshot(job)
    assert s["state"] == "finished", s["error"]
    done = [c for c in s["candidates"] if c["status"] == "finished" and c["feasible"]]
    same = [c for c in done if c["parts"] == [f"{GENERIC}:{a.part}", f"{GENERIC}:{b.part}"]]
    assert same, [c["parts"] for c in done]
    # the original parts recover their spacing; another stock choice may do better (e.g. a best-form lens)
    sysb = OpticalSystem.model_validate(jobs.candidate(job, same[0]["index"])["project"]["system"])
    gap = [x.thickness for x in sysb.surfaces if x.label == f"{a.part} back"][0]
    assert gap == pytest.approx(12.0, abs=1.5)
    assert min(c["metrics"]["merit"] for c in done) <= same[0]["metrics"]["merit"]


def test_match_refuses_designs_without_lens_elements():
    from opticore.samples import get_sample

    p = get_sample("spherical-mirror")
    r = client.post("/api/v1/stock/match/start", json={"system": p.system.model_dump(mode="json"), "custom_materials": []})
    assert r.status_code == 422 and r.json()["error"]["code"] == "STOCK_DESIGN"
