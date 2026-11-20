"""Thumbnail outlines for the start screen: drawing data taken from the exact layout geometry and trace."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.evaluate import evaluate_system
from opticore.analysis.outline import system_outline
from opticore.api.main import app
from opticore.samples import CATEGORY_ORDER, SAMPLE_CATEGORIES, SAMPLES, list_samples, singlet, spherical_mirror
from opticore.system import compile_system

client = TestClient(app)


def test_every_sample_has_a_start_screen_group_and_an_outline():
    assert set(SAMPLE_CATEGORIES) == set(SAMPLES)
    listing = list_samples()
    assert [s["id"] for s in listing] == list(SAMPLES)
    for s in listing:
        assert s["category"] in CATEGORY_ORDER
        o = s["outline"]
        assert o is not None, s["id"]
        zmin, zmax, ymin, ymax = o["bbox"]
        assert zmax > zmin and ymax > ymin
        assert o["items"] and o["rays"]
        for it in o["items"] + o["rays"]:
            for z, y in it["points"]:
                assert zmin - 1e-6 * abs(zmin) - 1e-9 <= z <= zmax + 1e-6 * abs(zmax) + 1e-9
                assert ymin - 1e-6 * abs(ymin) - 1e-9 <= y <= ymax + 1e-6 * abs(ymax) + 1e-9


def test_singlet_outline_follows_the_prescription_and_the_trace():
    p = singlet()
    cs = compile_system(p.system, p.custom_materials)
    o = system_outline(cs)
    glass = [it for it in o["items"] if it["kind"] == "glass"]
    assert len(glass) == 1
    z = np.array([q[0] for q in glass[0]["points"]])
    y = np.array([q[1] for q in glass[0]["points"]])
    surfs = p.system.surfaces
    t1 = surfs[1].thickness
    r1 = surfs[1].radius
    # front vertex at z = 0, plane back face at z = centre thickness
    assert z.min() == pytest.approx(0.0, abs=1e-9)
    assert z.max() == pytest.approx(t1, rel=1e-5)
    # the front profile lies on the sphere of radius R1 (sag z = R - sqrt(R^2 - y^2)), up to its
    # semi-diameter (beyond it the outline steps out to the larger back face)
    ev = evaluate_system(cs, 3, 0)
    h1 = ev["semi_diameters"][1]
    front = [(zz, yy) for zz, yy in zip(z, y) if zz < t1 * 0.999 and abs(yy) <= h1 * (1 + 1e-4)]
    assert len(front) >= 10
    for zz, yy in front:
        assert zz == pytest.approx(r1 - np.sqrt(r1 * r1 - yy * yy), abs=1e-4 * max(1.0, abs(zz)))
    # rays: the same real rays as the layout trace (primary wavelength), ending on the image plane
    zi = ev["global_vertex_z"][-1]
    ref = [r for r in ev["rays"] if r["wavelength"] == p.system.primary_wavelength and r["field"] == 0]
    mine = [r for r in o["rays"] if r["field"] == 0]
    assert len(mine) == len(ref) == 3
    for a, b in zip(mine, ref):
        assert a["ok"]
        assert a["points"][-1][0] == pytest.approx(zi, rel=1e-4)
        assert a["points"][-1][1] == pytest.approx(b["points"][-1][1], abs=1e-4)
    # object at infinity: the rays start in front of the lens, at the left edge of the box
    assert o["infinite_object"]
    assert min(r["points"][0][0] for r in o["rays"]) == pytest.approx(o["bbox"][0], abs=1e-6)
    assert o["bbox"][0] < 0


def test_mirror_and_stop_items():
    p = spherical_mirror()
    o = system_outline(compile_system(p.system, p.custom_materials))
    kinds = [it["kind"] for it in o["items"]]
    assert kinds.count("mirror") == 1
    assert "image" in kinds


def test_outline_endpoint():
    p = singlet()
    r = client.post("/api/v1/system/outline", json={"system": p.system.model_dump(mode="json"), "custom_materials": []})
    assert r.status_code == 200
    body = r.json()
    assert {"bbox", "items", "rays", "infinite_object"} <= set(body)
    listing = client.get("/api/v1/samples").json()["samples"]
    assert all("category" in s and "outline" in s for s in listing)
    bad = p.system.model_dump(mode="json")
    bad["surfaces"] = bad["surfaces"][:1]
    assert client.post("/api/v1/system/outline", json={"system": bad, "custom_materials": []}).status_code == 422
