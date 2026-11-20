"""Neutral test systems for the beam tests: a Gaussian source, one or two lenses and a detector.

These are not library samples. They give the physical-optics, BPM, direct-path and
detector-operand tests systems with a known first-order layout:
* `relay()`: a 1:1 relay of two AR-coated plano-convex N-BK7 lenses (f = 25 mm) at 1.064 um; the
  beam is collimated and wide between the lenses.
* `thick_lens(s)`: a strongly curved N-SF11 biconvex lens (R = +-2.5 mm, 2.8 mm thick) at 1.55 um,
  source and detector 9 mm apart, too close for a sharp image (1:1 needs 2 (f + BFL) = 6.73 mm of
  air, 6.2 mm are left), so the spot size has one minimum over the source distance s and a larger
  target spot two solutions; s is the optimisation variable, and a pickup keeps the length.
* `singlet()`: an AR-coated N-BK7 biconvex lens (R = +-5 mm) at 1.55 um.

The first-order data are derived from the thick-lens equations in the tests that use them.
"""

from __future__ import annotations

import math

from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.nssources import Detector, LightSource
from opticore.optimize.merit import OptimizationSpec
from opticore.project import Metadata, Project

THICK_LENS_LENGTH = 9.0
THICK_LENS_TARGET = 0.120  # D4sigma on the detector (mm)


def ar(lam_um: float) -> dict:
    """A quarter-wave MgF2 (n = 1.38) antireflection layer for lam_um."""
    return {
        "name": f"AR_{round(lam_um * 1000)}",
        "description": f"Quarter-wave MgF2 antireflection layer for {lam_um * 1000:g} nm",
        "layers": [{"material": "", "index": 1.38, "extinction": 0.0, "thickness_nm": round(lam_um * 1000 / (4 * 1.38), 2)}],
        "substrate_index": None,
        "substrate_extinction": 0.0,
    }


def gaussian_source(lam_um: float, w0_mm: float, placement: dict, rays: int = 1500) -> LightSource:
    theta = math.degrees(math.atan(lam_um * 1e-3 / (math.pi * w0_mm)))
    return LightSource(
        id="src",
        name="Gaussian source",
        placement=placement,
        shape="disk",
        size_x=5 * w0_mm,
        spatial="gaussian",
        gaussian_wx=w0_mm,
        gaussian_wy=w0_mm,
        angular="gaussian",
        gaussian_x_deg=round(theta, 4),
        gaussian_y_deg=round(theta, 4),
        rays=rays,
        power_w=0.001,
        wavelengths=[{"value": lam_um, "weight": 1.0}],
    )


RELAY_LAM = 1.064
RELAY_F = 25.0
RELAY_T = 4.0
RELAY_GAP = 5.0
RELAY_W0 = 0.004


def relay() -> Project:
    """Source at the front focal point of L1 (plane side first), collimated between the lenses, image at
    the back focal point of L2: magnification -1. R = f (n - 1); the focal distance from the plane
    face is f - t / n."""
    n = MaterialLibrary().index("N-BK7", RELAY_LAM)
    R = RELAY_F * (n - 1)
    d0 = RELAY_F - RELAY_T / n
    coat = ar(RELAY_LAM)
    sd = dict(semi_diameter=8.0, semi_diameter_mode="fixed", coating=coat["name"])
    sys = OpticalSystem.model_validate(
        {
            "name": "Gaussian relay (test)",
            "surfaces": [
                {"id": "obj", "thickness": d0},
                {"id": "l1a", "radius": None, "thickness": RELAY_T, "material": "N-BK7", **sd},
                {"id": "l1b", "radius": -R, "thickness": RELAY_GAP, "is_stop": True, **sd},
                {"id": "l2a", "radius": R, "thickness": RELAY_T, "material": "N-BK7", **sd},
                {"id": "l2b", "radius": None, "thickness": d0, **sd},
                {"id": "img"},
            ],
            "wavelengths": [{"value": RELAY_LAM}],
            "field_type": "object_height",
            "fields": [{"y": 0.0}, {"y": 0.05}],
            "aperture": {"type": "object_na", "value": 0.1},
            "custom_coatings": [coat],
        }
    )
    detectors = [
        Detector(id="det", name="Detector Ø0.5 mm", placement={"anchor": "img"}, shape="circle", size_x=0.25, pixels=48),
        Detector(id="mon", name="Collimated beam (monitor)", placement={"anchor": "l1b", "position": [0.0, 0.0, RELAY_GAP / 2]}, shape="circle", size_x=7.0, mode="monitor", pixels=48),
    ]
    return Project(metadata=Metadata(name="Gaussian relay (test)"), system=sys, sources=[gaussian_source(RELAY_LAM, RELAY_W0, {"anchor": "obj"})], detectors=detectors)


THICK_R = 2.5
THICK_T = 2.8
THICK_LAM = 1.55
THICK_W0 = 0.0052


def thick_lens(s: float = 2.4) -> Project:
    """Source s before a strongly curved N-SF11 biconvex lens; the detector stays THICK_LENS_LENGTH from
    the source (a pickup sets the back distance). Detector operands: the D4sigma on the detector and
    the power on it, the source distance as the variable."""
    coat = ar(THICK_LAM)
    sd = dict(semi_diameter=1.5, semi_diameter_mode="fixed", coating=coat["name"])
    L, t = THICK_LENS_LENGTH, THICK_T
    sys = OpticalSystem.model_validate(
        {
            "name": "Thick lens beam (test)",
            "surfaces": [
                {"id": "obj", "thickness": s},
                {"id": "a", "radius": THICK_R, "thickness": t, "material": "N-SF11", "is_stop": True, **sd},
                {"id": "b", "radius": -THICK_R, "thickness": L - t - s, "thickness_solve": {"type": "pickup", "surface_id": "obj", "scale": -1.0, "offset": L - t}, **sd},
                {"id": "img"},
            ],
            "wavelengths": [{"value": THICK_LAM}],
            "field_type": "object_height",
            "fields": [{"y": 0.0}, {"y": 0.005}],
            "aperture": {"type": "object_na", "value": 0.0949},
            "custom_coatings": [coat],
        }
    )
    detectors = [
        Detector(id="det", name="Detector Ø0.4 mm", placement={"anchor": "img"}, shape="circle", size_x=0.2, pixels=48),
        Detector(id="mon", name="Beam on the lens (monitor)", placement={"anchor": "a", "position": [0.0, 0.0, -0.05]}, shape="circle", size_x=1.5, mode="monitor", pixels=48),
    ]
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "obj", "parameter": "thickness", "min": 0.3, "max": 5.9}],
            "operands": [
                {"type": "detector_size", "detector_id": "det", "target": THICK_LENS_TARGET, "weight": 1.0},
                {"type": "detector_power", "detector_id": "det", "target": 1.0, "weight": 0.1},
            ],
            "algorithm": "local",
            "max_evaluations": 400,
        }
    )
    return Project(
        metadata=Metadata(name="Thick lens beam (test)"),
        system=sys,
        sources=[gaussian_source(THICK_LAM, THICK_W0, {"anchor": "obj"})],
        detectors=detectors,
        optimization=spec,
    )


def singlet() -> Project:
    """Source 8 mm before an AR-coated N-BK7 biconvex lens (R = +-5 mm, 2 mm thick), detector 12 mm behind."""
    lam = 1.55
    coat = ar(lam)
    sd = dict(semi_diameter=1.8, semi_diameter_mode="fixed", coating=coat["name"])
    sys = OpticalSystem.model_validate(
        {
            "name": "Singlet beam (test)",
            "surfaces": [
                {"id": "obj", "thickness": 8.0},
                {"id": "a", "radius": 5.0, "thickness": 2.0, "material": "N-BK7", "is_stop": True, **sd},
                {"id": "b", "radius": -5.0, "thickness": 12.0, **sd},
                {"id": "img"},
            ],
            "wavelengths": [{"value": lam}],
            "field_type": "object_height",
            "fields": [{"y": 0.0}, {"y": 0.02}],
            "aperture": {"type": "object_na", "value": 0.0949},
            "custom_coatings": [coat],
        }
    )
    detectors = [Detector(id="det", name="Detector Ø0.4 mm", placement={"anchor": "img"}, shape="circle", size_x=0.2, pixels=48)]
    return Project(metadata=Metadata(name="Singlet beam (test)"), system=sys, sources=[gaussian_source(lam, THICK_W0, {"anchor": "obj"})], detectors=detectors)
