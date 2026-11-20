"""Built-in sample designs (original designs created for OptiCore Studio, and published reference designs
transcribed from public prescriptions).

Each sample documents how it was derived so its results can be reproduced.
"""

from __future__ import annotations

import math
from functools import lru_cache

from .model import OpticalSystem
from .nssources import Detector, LightSource
from .optimize.merit import OptimizationSpec
from .project import Metadata, Project

FDC = [{"value": 0.4861327, "weight": 1.0}, {"value": 0.5875618, "weight": 1.0}, {"value": 0.6562725, "weight": 1.0}]


def _s(**kw) -> dict:
    return kw


def singlet() -> Project:
    """Plano-convex N-BK7 singlet, f = 100 mm at d-line (R = f (nd - 1))."""
    sys = OpticalSystem.model_validate(
        {
            "name": "Plano-convex singlet f=100",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="s1", label="Front", radius=51.68, thickness=5.0, material="N-BK7", is_stop=True, semi_diameter=12.7),
                _s(id="s2", label="Back", radius=None, thickness=96.7036),
                _s(id="img", label="Image"),
            ],
            "wavelengths": FDC,
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}, {"y": 2.0}, {"y": 4.0}],
            "aperture": {"type": "epd", "value": 10.0},
        }
    )
    return Project(
        metadata=Metadata(
            name="Plano-convex singlet",
            description="N-BK7 plano-convex lens, R1 = f (nd - 1) for f = 100 mm. Image at the paraxial focus (d line).",
        ),
        system=sys,
    )


ACHROMAT_START = {
    # Thin-lens achromat (N-BK7 / F2, f = 100 mm, equiconvex crown):
    # phi1 = phi V1/(V1-V2), phi2 = -phi V2/(V1-V2) with V1 = 64.17, V2 = 36.37
    "R1": 44.78,
    "R2": -44.78,
    "R3": -811.0,
}


def achromat(optimized: bool = True) -> Project:
    """Cemented achromatic doublet f = 100 mm, F/5, N-BK7 / F2.

    Start: thin-lens achromat solution (see ACHROMAT_START). The optimised
    variant was produced by OptiCore's own least-squares optimiser
    (variables R1, R2, R3, image distance; operands RMS spot over F,d,C and
    three fields, EFL = 100 mm, paraxial axial colour F-C = 0, minimum edge
    thickness). Values are frozen here as the regression baseline."""
    if optimized:
        r1, r2, r3, bfd = OPT_ACHROMAT["R1"], OPT_ACHROMAT["R2"], OPT_ACHROMAT["R3"], OPT_ACHROMAT["BFD"]
    else:
        r1, r2, r3, bfd = ACHROMAT_START["R1"], ACHROMAT_START["R2"], ACHROMAT_START["R3"], 95.0
    sys = OpticalSystem.model_validate(
        {
            "name": "Achromatic doublet f=100 F/5",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="d1", label="Crown front", radius=r1, thickness=6.0, material="N-BK7", is_stop=True, semi_diameter=12.5),
                _s(id="d2", label="Cemented", radius=r2, thickness=2.5, material="F2", semi_diameter=12.5),
                _s(id="d3", label="Flint back", radius=r3, thickness=bfd, semi_diameter=12.5),
                _s(id="img", label="Image"),
            ],
            "wavelengths": FDC,
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}, {"y": 1.4}, {"y": 2.0}],
            "aperture": {"type": "epd", "value": 20.0},
        }
    )
    spec = OptimizationSpec.model_validate(
        {
            "variables": [
                {"surface_id": "d1", "parameter": "curvature", "min": -0.1, "max": 0.1},
                {"surface_id": "d2", "parameter": "curvature", "min": -0.1, "max": 0.1},
                {"surface_id": "d3", "parameter": "curvature", "min": -0.1, "max": 0.1},
                {"surface_id": "d3", "parameter": "thickness", "min": 50.0, "max": 150.0},
            ],
            "operands": [
                {"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 4},
                {"type": "efl", "target": 100.0, "weight": 1.0},
                {"type": "axial_color", "target": 0.0, "weight": 0.05},
                {"type": "min_edge_thickness", "surface_id": "d1", "target": 1.5, "weight": 1.0},
            ],
            "algorithm": "local",
            "max_evaluations": 3000,
        }
    )
    name = "Achromatic doublet (optimized)" if optimized else "Achromatic doublet (thin-lens start)"
    desc = (
        "Cemented N-BK7/F2 doublet, f = 100 mm, F/5, 2 deg half field. "
        + ("Optimised with OptiCore least squares." if optimized else "Thin-lens achromat starting point; run Optimize to correct spherical aberration.")
    )
    return Project(metadata=Metadata(name=name, description=desc), system=sys, optimization=spec)


# Frozen output of OptiCore's local optimiser (least_squares/trf) run on
# achromat(optimized=False) with its stored OptimizationSpec (149 evaluations,
# Gaussian-quadrature pupil sampling; weighted merit 0.3453 -> 0.00672. With exact limits (ADR-042, the default)
# the run reaches the same design to 5e-5 and reports the goals' merit, 0.011453).
# Reproduce with:  python -m opticore.tools.reoptimize_sample achromat-start
OPT_ACHROMAT = {"R1": 49.5259, "R2": -38.6718, "R3": -276.2582, "BFD": 94.8055}


def spherical_mirror() -> Project:
    """Concave spherical mirror R = -200 mm (paraxial focus at R/2)."""
    sys = OpticalSystem.model_validate(
        {
            "name": "Spherical mirror f=100",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="m0", label="Entrance", radius=None, thickness=50.0, is_stop=True),
                _s(id="m1", label="Mirror", radius=-200.0, thickness=-100.0, material="MIRROR", semi_diameter=15.0),
                _s(id="img", label="Image"),
            ],
            "wavelengths": [{"value": 0.5875618}],
            "fields": [{"y": 0.0}, {"y": 0.5}],
            "aperture": {"type": "epd", "value": 20.0},
        }
    )
    return Project(metadata=Metadata(name="Spherical mirror", description="Concave mirror R = -200 mm, F/5. Image at the paraxial focus."), system=sys)


def fold_mirror() -> Project:
    """Singlet followed by a 45 degree fold mirror (coordinate breaks)."""
    sys = OpticalSystem.model_validate(
        {
            "name": "Folded singlet",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="f1", label="Lens front", radius=51.68, thickness=5.0, material="N-BK7", is_stop=True),
                _s(id="f2", label="Lens back", radius=None, thickness=40.0),
                _s(id="cb1", type="coordinate_break", label="Tilt in", thickness=0.0, tilt_x=45.0),
                _s(id="fm", label="Fold mirror", radius=None, thickness=0.0, material="MIRROR", semi_diameter=12.0),
                _s(id="cb2", type="coordinate_break", label="Tilt out", thickness=-56.7036, tilt_x=45.0),
                _s(id="img", label="Image"),
            ],
            "wavelengths": [{"value": 0.5875618}],
            "fields": [{"y": 0.0}, {"y": 2.0}],
            "aperture": {"type": "epd", "value": 10.0},
        }
    )
    return Project(
        metadata=Metadata(
            name="Folded singlet",
            description="Plano-convex singlet with a 45 degree fold mirror built from two coordinate breaks.",
        ),
        system=sys,
    )


TRIPLET_START = {"t1": 22.0, "t2": -400.0, "t3": -40.0, "t4": 20.0, "t5": 80.0, "t6": -30.0, "g1": 4.5, "g2": 1.8, "g3": 3.0, "bfd": 42.0}
# Frozen output of the local optimiser on cooke_triplet(optimized=False); reproduce with
#   python -m opticore.tools.reoptimize_sample cooke-triplet-start
OPT_TRIPLET = {"t1": 22.796481, "t2": -327.973767, "t3": -22.679154, "t4": 20.698417, "t5": 79.034080, "t6": -18.605636, "g1": 5.869512, "g2": 0.852205, "g3": 3.941945, "bfd": 42.307135}
# (1255 evaluations; weighted merit 4.466 -> 0.00536; with exact limits the same design to 5e-5, goals' merit 0.0141808)


def cooke_triplet(optimized: bool = True) -> Project:
    """Cooke triplet f = 50 mm, F/4.5, +-20 deg, N-SK16 / F2 / N-SK16 (original design).

    Starting point: rough classic triplet proportions. The optimised variant was
    produced by OptiCore's least-squares optimiser with real ray aiming
    (variables: six curvatures, two air spaces, stop position and image
    distance; operands: polychromatic RMS spot over three fields, EFL = 50 mm,
    minimum edge thicknesses and a weak distortion target)."""
    v = OPT_TRIPLET if optimized else TRIPLET_START
    sys = OpticalSystem.model_validate(
        {
            "name": "Cooke triplet f=50 F/4.5",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="t1", label="L1 front", radius=v["t1"], thickness=3.5, material="N-SK16"),
                _s(id="t2", label="L1 back", radius=v["t2"], thickness=v["g1"]),
                _s(id="t3", label="L2 front", radius=v["t3"], thickness=1.2, material="F2"),
                _s(id="t4", label="L2 back", radius=v["t4"], thickness=v["g2"]),
                _s(id="stp", label="Stop", radius=None, thickness=v["g3"], is_stop=True),
                _s(id="t5", label="L3 front", radius=v["t5"], thickness=3.0, material="N-SK16"),
                _s(id="t6", label="L3 back", radius=v["t6"], thickness=v["bfd"]),
                _s(id="img", label="Image"),
            ],
            "wavelengths": FDC,
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}, {"y": 14.0}, {"y": 20.0}],
            "aperture": {"type": "image_fnum", "value": 4.5},
            "ray_aiming": "real",
        }
    )
    var = [{"surface_id": sid, "parameter": "curvature", "min": -0.12, "max": 0.12} for sid in ("t1", "t2", "t3", "t4", "t5", "t6")]
    var += [
        {"surface_id": "t2", "parameter": "thickness", "min": 1.0, "max": 12.0},
        {"surface_id": "t4", "parameter": "thickness", "min": 0.5, "max": 8.0},
        {"surface_id": "stp", "parameter": "thickness", "min": 0.5, "max": 8.0},
        {"surface_id": "t6", "parameter": "thickness", "min": 30.0, "max": 60.0},
    ]
    ops = [
        {"type": "rms_spot", "rings": 4, "weight": 1.0},
        {"type": "efl", "target": 50.0, "weight": 1.0},
        {"type": "min_edge_thickness", "surface_id": "t1", "target": 1.0, "weight": 1.0},
        {"type": "min_edge_thickness", "surface_id": "t5", "target": 1.0, "weight": 1.0},
        {"type": "min_edge_thickness", "surface_id": "t3", "target": 1.0, "weight": 1.0},
        {"type": "min_edge_thickness", "surface_id": "t2", "target": 0.5, "weight": 1.0},
        {"type": "min_edge_thickness", "surface_id": "t4", "target": 0.3, "weight": 1.0},
        {"type": "distortion", "target": 0.0, "weight": 0.002},
    ]
    spec = OptimizationSpec.model_validate({"variables": var, "operands": ops, "algorithm": "local", "max_evaluations": 6000})
    name = "Cooke triplet (optimized)" if optimized else "Cooke triplet (rough start)"
    desc = "Air-spaced N-SK16/F2/N-SK16 triplet, f = 50 mm, F/4.5, 20 deg half field. " + (
        "Optimised with OptiCore least squares (real ray aiming)." if optimized else "Rough starting point; run Optimize (about 2-3 minutes)."
    )
    return Project(metadata=Metadata(name=name, description=desc), system=sys, optimization=spec)


# Back-focus distances for the two-conjugate sample: each found by OptiCore's
# optimiser (RMS spot over F, d, C and three fields with only that
# configuration's back focus free); frozen as regression baselines.
TWO_CONJ_BFD = {"inf": 94.8055, "500": 119.387759}


def achromat_two_conjugates() -> Project:
    """The optimised achromat used at two conjugates (multi-configuration).

    Configuration 1: object at infinity. Configuration 2: object 500 mm in
    front of the lens. The object distance and the back focus differ per
    configuration; the merit function contains one RMS-spot operand per
    configuration and the back focus is a per-configuration variable, so a
    single optimisation refocuses both."""
    base = achromat(True)
    d = base.system.model_dump()
    d["name"] = "Achromat at two conjugates"
    d["multi_config"] = {
        "names": ["Object at infinity", "Object at 500 mm"],
        "active": 0,
        "operands": [
            {"parameter": "thickness", "surface_id": "obj", "values": [None, 500.0]},
            {"parameter": "thickness", "surface_id": "d3", "values": [TWO_CONJ_BFD["inf"], TWO_CONJ_BFD["500"]]},
        ],
    }
    sys = OpticalSystem.model_validate(d)
    spec = OptimizationSpec.model_validate(
        {
            "variables": [
                {"surface_id": "d3", "parameter": "thickness", "min": 50.0, "max": 200.0, "configuration": 0},
                {"surface_id": "d3", "parameter": "thickness", "min": 50.0, "max": 200.0, "configuration": 1},
            ],
            "operands": [
                {"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 4, "configuration": 0},
                {"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 4, "configuration": 1},
            ],
            "algorithm": "local",
            "max_evaluations": 500,
        }
    )
    return Project(
        metadata=Metadata(
            name="Achromat at two conjugates",
            description="Multi-configuration example: the optimised N-BK7/F2 achromat focused for an object at infinity and at 500 mm (object distance and back focus per configuration).",
        ),
        system=sys,
        optimization=spec,
    )


# HOYA glasses of the double Gauss (HOYA Zemax catalogue 2017-04-01 via refractiveindex.info, CC0):
# refractiveindex.info formula 3 = OptiCore "polynomial" n^2 = A + sum c_i L^e_i
HOYA_LAF3 = {
    "name": "LAF3",
    "formula": "polynomial",
    "coefficients": [2.8789799, -0.008729237, 2, 0.024425656, -2, 4.5491773e-05, -4, 4.2802928e-05, -6, -7.2834306e-07, -8],
    "lambda_min": 0.36501,
    "lambda_max": 1.01398,
    "family": "HOYA",
    "category": "glass",
    "catalog": "HOYA",
    "nd_ref": 1.71700,
    "vd_ref": 47.98,
    "density": 4.2,
    "dpgf": -0.0063,
    "source": "HOYA Zemax catalogue 2017-04-01 (glass code 717480), via refractiveindex.info (CC0)",
}
HOYA_BAF11 = {
    "name": "BAF11",
    "formula": "polynomial",
    "coefficients": [2.7272955, -0.013470236, 2, 0.014809271, -2, 0.0019615335, -4, -0.00019787663, -6, 1.0851117e-05, -8],
    "lambda_min": 0.36501,
    "lambda_max": 1.01398,
    "family": "HOYA",
    "category": "glass",
    "catalog": "HOYA",
    "nd_ref": 1.66672,
    "vd_ref": 48.30,
    "density": 3.63,
    "dpgf": 0.0022,
    "comment": "Discontinued by HOYA",
    "source": "HOYA Zemax catalogue 2017-04-01 (glass code 667483), via refractiveindex.info (CC0)",
}


def double_gauss() -> Project:
    """Double Gauss f/1.7, f = 100.2 mm, +-19 deg (Lautebacher & Brendel, US 2,784,643, Agfa), as tabulated in
    W. J. Smith, Modern Lens Design, 2nd ed. (2005), p. 323, with the glasses HOYA LAF3, HOYA BAF11 and SCHOTT
    N-SF5 used in COMSOL's Ray Optics tutorial of the same lens. Radii, thicknesses and clear radii (fixed
    apertures, so the vignetting is the design's) as published; the image surface is at the published
    61.418 mm back focus. Checks (tests/test_reference_designs.py): EFL 100.2 mm, F/1.70, paraxial back focus
    61.42 mm, and the 550 nm on-axis best RMS focus 186 um before the image surface (COMSOL: 187 um)."""
    fixed = {"semi_diameter_mode": "fixed"}
    sys = OpticalSystem.model_validate(
        {
            "name": "Double Gauss f/1.7, 100 mm",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="l1a", label="L1 front", radius=75.05, thickness=9.0, material="LAF3", semi_diameter=33.0, **fixed),
                _s(id="l1b", label="L1 back", radius=270.7, thickness=0.1, semi_diameter=33.0, **fixed),
                _s(id="l2a", label="L2 front", radius=39.27, thickness=16.51, material="BAF11", semi_diameter=27.5, **fixed),
                _s(id="l2b", label="L2 | L3 cemented", radius=None, thickness=2.0, material="N-SF5", semi_diameter=24.5, **fixed),
                _s(id="l3b", label="L3 back", radius=25.65, thickness=10.99, semi_diameter=19.5, **fixed),
                _s(id="stop", label="Stop", radius=None, thickness=13.0, is_stop=True, semi_diameter=18.6, **fixed),
                _s(id="l4a", label="L4 front", radius=-31.87, thickness=7.03, material="N-SF5", semi_diameter=18.5, **fixed),
                _s(id="l4b", label="L4 | L5 cemented", radius=None, thickness=8.98, material="LAF3", semi_diameter=21.0, **fixed),
                _s(id="l5b", label="L5 back", radius=-43.51, thickness=0.1, semi_diameter=21.0, **fixed),
                _s(id="l6a", label="L6 front", radius=221.14, thickness=7.98, material="BAF11", semi_diameter=23.0, **fixed),
                _s(id="l6b", label="L6 back", radius=-88.79, thickness=61.418, semi_diameter=23.0, **fixed),
                _s(id="img", label="Image", semi_diameter=42.5, **fixed),
            ],
            "wavelengths": FDC,
            "primary_wavelength": 1,
            # vignetting factors from analysis.vignetting (rounded inwards): the marginal rays of every field just pass
            "fields": [
                {"y": 0.0},
                {"y": 10.0, "vdy": -0.0369, "vcy": 0.1655},
                {"y": 14.0, "vdy": -0.0691, "vcx": 0.0215, "vcy": 0.2862},
                {"y": 19.0, "vdy": -0.1524, "vcx": 0.0713, "vcy": 0.4978},
            ],
            "field_type": "angle",
            "aperture": {"type": "epd", "value": 58.941},
        }
    )
    return Project(
        metadata=Metadata(
            name="Double Gauss f/1.7, 100 mm (US 2,784,643)",
            description="Six-element double Gauss photographic objective by Lautebacher & Brendel (Agfa, US patent 2,784,643): f = 100.2 mm, f/1.7, ±19° field, "
            "two cemented doublets around the stop. Prescription and clear apertures as tabulated in W. J. Smith, Modern Lens Design (2005), p. 323; "
            "glasses HOYA LAF3 and BAF11 (HOYA catalogue 2017 via refractiveindex.info) and SCHOTT N-SF5, as in COMSOL's Ray Optics tutorial of this lens. "
            "A published reference design, not optimised here: EFL 100.2 mm and the 550 nm best focus 186 µm before the image surface agree with the sources (COMSOL: 187 µm). "
            "The fixed clear apertures vignette the full field (about 40 % of the pupil passes at 19°), as in the original; the fields carry vignetting factors "
            "(Set vignetting), so spot diagrams, fans and the layout sample the part of the pupil that passes.",
        ),
        system=sys,
        custom_materials=[dict(HOYA_LAF3), dict(HOYA_BAF11)],
    )


# SCHOTT glasses not in the built-in list (SCHOTT Zemax catalogue 2017-01-20b via refractiveindex.info, CC0)
_SCHOTT_SRC = "SCHOTT Zemax catalogue 2017-01-20b, via refractiveindex.info (CC0)"
SCHOTT_N_LAK9 = {"name": "N-LAK9", "formula": "sellmeier", "coefficients": [1.46231905, 0.00724270156, 0.344399589, 0.0243353131, 1.15508372, 85.4686868], "lambda_min": 0.3, "lambda_max": 2.5, "family": "SCHOTT", "category": "glass", "catalog": "SCHOTT", "nd_ref": 1.691, "vd_ref": 54.71, "density": 3.51, "dpgf": -0.0071, "source": _SCHOTT_SRC}
SCHOTT_N_KZFS5 = {"name": "N-KZFS5", "formula": "sellmeier", "coefficients": [1.47460789, 0.00986143816, 0.193584488, 0.0445477583, 1.26589974, 106.436258], "lambda_min": 0.334, "lambda_max": 2.5, "family": "SCHOTT", "category": "glass", "catalog": "SCHOTT", "nd_ref": 1.65412, "vd_ref": 39.70, "density": 3.041, "dpgf": -0.006, "source": _SCHOTT_SRC}
SCHOTT_N_SK2 = {"name": "N-SK2", "formula": "sellmeier", "coefficients": [1.28189012, 0.0072719164, 0.257738258, 0.0242823527, 0.96818604, 110.377773], "lambda_min": 0.31, "lambda_max": 2.5, "family": "SCHOTT", "category": "glass", "catalog": "SCHOTT", "nd_ref": 1.60738, "vd_ref": 56.65, "density": 3.55, "dpgf": -0.0008, "source": _SCHOTT_SRC}


def geiser_triplet() -> Project:
    """Cooke triplet f/4, f = 50 mm, +-20 deg (Geiser), the triplet of J. Sasian's OPTI 517 course as entered in the
    ray-optics documentation example "Triplet example" (N-LAK9 / N-SF5 / N-LAK9). The ray-optics output (first-order
    data, paraxial ray heights, surface Seidel sums) is an independent reference (tests/test_reference_designs.py)."""
    sys = OpticalSystem.model_validate(
        {
            "name": "Geiser triplet f/4, 50 mm",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="g1", label="L1 front", radius=23.713, thickness=4.831, material="N-LAK9"),
                _s(id="g2", label="L1 back", radius=7331.288, thickness=5.86),
                _s(id="g3", label="L2 front (stop)", radius=-24.456, thickness=0.975, material="N-SF5", is_stop=True),
                _s(id="g4", label="L2 back", radius=21.896, thickness=4.822),
                _s(id="g5", label="L3 front", radius=86.759, thickness=3.127, material="N-LAK9"),
                _s(id="g6", label="L3 back", radius=-20.4942, thickness=41.2365),
                _s(id="img", label="Image"),
            ],
            "wavelengths": [{"value": 0.4861327, "weight": 0.5}, {"value": 0.5875618, "weight": 1.0}, {"value": 0.6562725, "weight": 0.5}],
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}, {"y": 14.142}, {"y": 20.0}],
            "field_type": "angle",
            "aperture": {"type": "epd", "value": 12.5},
        }
    )
    return Project(
        metadata=Metadata(
            name="Geiser triplet f/4, 50 mm (Sasián / ray-optics)",
            description="Cooke triplet by Geiser: f = 50 mm, f/4, ±20°, N-LAK9 / N-SF5 / N-LAK9, the stop on the front of the negative lens, image at the paraxial focus. "
            "Prescription as in J. Sasián's OPTI 517 lens-design course and the ray-optics documentation example; the ray-optics first-order data, paraxial ray heights and "
            "surface Seidel sums are reproduced to the printed digits (independent software). A published reference design, not optimised here.",
        ),
        system=sys,
        custom_materials=[dict(SCHOTT_N_LAK9)],
    )


def petzval_kidger() -> Project:
    """Petzval objective with a field flattener, f = 100 mm, f/2.4, +-9 deg (M. Kidger, Fundamental Optical Design,
    2001, p. 192) as modelled in COMSOL's Ray Optics tutorial "Petzval Lens" (glasses N-BK7, N-KZFS5, N-SK2,
    N-SF5; some replaced by COMSOL, and the back focus set to the polychromatic best focus). Clear radii fixed as
    tabulated."""
    fixed = {"semi_diameter_mode": "fixed"}
    sys = OpticalSystem.model_validate(
        {
            "name": "Petzval f/2.4, 100 mm",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                _s(id="p1", label="L1 front", radius=98.45049, thickness=13.0, material="N-BK7", semi_diameter=28.478, **fixed),
                _s(id="p2", label="L1 | L2 cemented", radius=-83.29386, thickness=4.0, material="N-KZFS5", semi_diameter=26.267, **fixed),
                _s(id="p3", label="L2 back", radius=-1421.38828, thickness=40.0, semi_diameter=22.020, **fixed),
                _s(id="stop", label="Stop", radius=None, thickness=40.0, is_stop=True, semi_diameter=16.631, **fixed),
                _s(id="p4", label="L3 front", radius=59.00613, thickness=12.0, material="N-SK2", semi_diameter=20.543, **fixed),
                _s(id="p5", label="L3 | L4 cemented", radius=-54.3647, thickness=3.0, material="N-SF5", semi_diameter=20.074, **fixed),
                _s(id="p6", label="L4 back", radius=-549.36547, thickness=46.8221, semi_diameter=16.492, **fixed),
                _s(id="p7", label="Field flattener front", radius=-39.80076, thickness=2.0, material="N-SF5", semi_diameter=17.297, **fixed),
                _s(id="p8", label="Field flattener back", radius=None, thickness=1.9548, semi_diameter=18.940, **fixed),
                _s(id="img", label="Image", semi_diameter=17.904, **fixed),
            ],
            "wavelengths": [{"value": 0.475}, {"value": 0.55}, {"value": 0.625}],
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}, {"y": 6.0}, {"y": 9.0}],
            "field_type": "angle",
            "aperture": {"type": "epd", "value": 41.5},
        }
    )
    return Project(
        metadata=Metadata(
            name="Petzval f/2.4, 100 mm with field flattener (Kidger)",
            description="Petzval objective with a field flattener (M. Kidger, Fundamental Optical Design, 2001): two cemented doublets around the stop and a negative "
            "flattener just before the image, f ≈ 100 mm, f/2.4, ±9°, at 475/550/625 nm. Prescription, glasses and clear apertures as in COMSOL's Ray Optics tutorial "
            "(some glasses substituted there, so EFL = 100.8 mm; the image plane is the polychromatic best focus to 1 µm). A published reference design, not optimised here.",
        ),
        system=sys,
        custom_materials=[dict(SCHOTT_N_KZFS5), dict(SCHOTT_N_SK2)],
    )


# Canon JP2015094867A, Numerical Example 1 (17-119 mm F2.8-3.4): surface number -> (r, d, nd, vd, effective diameter);
# d = None for the zoom gaps (CANON_ZOOM_GAPS). Transcribed from the patent's table (tests/test_reference_designs.py).
CANON_ZOOM_TABLE = [
    (230.634, 3.00, 1.77250, 49.6, 88.27), (42.785, 29.54, None, None, 69.60), (-81.327, 2.40, 1.77250, 49.6, 67.89),
    (253.731, 0.63, None, None, 70.15), (152.980, 6.97, 1.95906, 17.5, 71.98), (-1363.977, 0.93, None, None, 72.45),
    (171.683, 11.17, 1.60311, 60.6, 75.01), (-119.665, 4.80, None, None, 75.24), (289.766, 10.63, 1.49700, 81.5, 74.30),
    (-121.912, 2.40, 1.84666, 23.8, 73.96), (-179.990, 0.15, None, None, 74.07), (135.831, 2.20, 1.84666, 23.8, 71.31),
    (55.886, 13.26, 1.43875, 94.9, 67.69), (490.455, 0.15, None, None, 67.35), (189.444, 6.24, 1.43387, 95.1, 67.25),
    (-460.145, 0.15, None, None, 67.32), (196.655, 8.96, 1.77250, 49.6, 67.62), (-133.427, None, None, None, 67.43),
    (55.041, 1.00, 2.00100, 29.1, 33.94), (23.647, 6.99, None, None, 29.92), (-74.271, 1.00, 1.72916, 54.7, 29.82),
    (65.150, 3.00, None, None, 29.09), (42.793, 6.54, 1.78472, 25.7, 29.21), (-52.868, 0.69, None, None, 28.61),
    (-41.519, 1.00, 1.83481, 42.7, 28.42), (-2429.214, None, None, None, 27.79), (-47.481, 1.00, 1.72916, 54.7, 27.05),
    (196.255, 2.71, 1.92286, 18.9, 28.28), (-525.842, None, None, None, 28.88), (None, 1.46, None, None, 34.40),
    (533.292, 5.59, 1.60311, 60.6, 35.35), (-47.782, 0.15, None, None, 35.89), (70.982, 7.73, 1.48749, 70.2, 35.93),
    (-45.653, 1.00, 2.00069, 25.5, 35.63), (-292.209, 0.15, None, None, 36.03), (34.078, 5.98, 1.58913, 61.1, 36.46),
    (198.440, 25.02, None, None, 35.85), (-612.903, 1.00, 1.88300, 40.8, 22.63), (27.609, 4.32, 1.92286, 18.9, 21.74),
    (-97.230, 3.05, None, None, 21.33), (-39.345, 1.00, 2.00069, 25.5, 19.35), (32.927, 1.64, None, None, 18.99),
    (56.013, 3.83, 1.48749, 70.2, 20.05), (-49.782, 8.94, None, None, 21.08), (46.857, 6.88, 1.48749, 70.2, 28.99),
    (-40.009, 0.15, None, None, 29.31), (75.878, 3.17, 1.48749, 70.2, 28.80), (12752.683, 2.19, None, None, 28.43),
    (-50.658, 1.00, 1.84666, 23.8, 28.39), (-136.174, 46.02, None, None, 28.63),
]
CANON_ZOOM_ASPHERES = {1: (3.77301, [3.05128e-7, 1.87256e-10, -1.41108e-13, 4.60119e-17, -6.36153e-21]),
                       8: (-3.64841, [3.34659e-7, 7.99224e-11, -5.42827e-14, 1.99335e-17, -5.62220e-21])}
CANON_ZOOM_GAPS = {18: (0.80, 41.30, 58.60), 26: (51.59, 8.60, 7.16), 29: (14.87, 17.35, 1.49)}
CANON_ZOOM_FNO = (2.80, 2.80, 3.40)
CANON_ZOOM_VIGNETTING = {  # (field, factor): per zoom position; analysis/vignetting.py, VD rounded, VC rounded up + 1e-4
    (1, "vdy"): [-0.1018, -0.0485, 0.1095],
    (1, "vcx"): [0.0336, 0.0634, 0.0704],
    (1, "vcy"): [0.2942, 0.3735, 0.4052],
    (2, "vdy"): [0.06, 0.1009, 0.0689],
    (2, "vcx"): [0.2236, 0.3448, 0.2481],
    (2, "vcy"): [0.6493, 0.8009, 0.6761],
}

# Catalogue glasses with the patent's (nd, vd) (refractiveindex.info, CC0); the coefficients reproduce the catalogue
# nd/Vd (OHARA to 1e-6, HOYA's fit to 3e-6). 1.43387 / 95.1 is fluorite, as a model glass through those values.
_OHARA_SRC = "OHARA catalogue via refractiveindex.info (CC0)"
_HOYA_SRC = "HOYA catalogue via refractiveindex.info (CC0)"
CANON_ZOOM_GLASSES = {
    (1.77250, 49.6): {"name": "S-LAH66", "formula": "sellmeier", "coefficients": [1.39280586, 0.00608475118, 0.679577094, 0.0233925351, 1.38702069, 95.8354094], "lambda_min": 0.31, "lambda_max": 2.4, "nd_ref": 1.772499, "vd_ref": 49.598371, "source": _OHARA_SRC},
    (1.95906, 17.5): {"name": "S-NPH3", "formula": "sellmeier", "coefficients": [2.09834903, 0.0179123869, 0.489088388, 0.0776653353, 2.94009268, 160.930428], "lambda_min": 0.36, "lambda_max": 2.4, "nd_ref": 1.959060, "vd_ref": 17.471252, "source": _OHARA_SRC},
    (1.60311, 60.6): {"name": "S-BSM14", "formula": "sellmeier", "coefficients": [1.2828627, 0.0122902399, 0.247647429, -0.00613142361, 1.10383999, 106.883378], "lambda_min": 0.31, "lambda_max": 2.4, "nd_ref": 1.603112, "vd_ref": 60.641080, "source": _OHARA_SRC},
    (1.49700, 81.5): {"name": "S-FPL51", "formula": "sellmeier", "coefficients": [1.17010505, 0.00616203924, 0.0475710783, 0.0263372876, 0.763832445, 141.882642], "lambda_min": 0.28, "lambda_max": 2.4, "nd_ref": 1.496999, "vd_ref": 81.545888, "source": _OHARA_SRC},
    (1.84666, 23.8): {"name": "S-TIH53", "formula": "sellmeier", "coefficients": [1.87904886, 0.014412177, 0.369719775, 0.063881799, 2.33730863, 182.66818], "lambda_min": 0.37, "lambda_max": 2.4, "nd_ref": 1.846660, "vd_ref": 23.777940, "source": _OHARA_SRC},
    (1.43875, 94.9): {"name": "S-FPL53", "formula": "sellmeier", "coefficients": [0.983532327, 0.00492234955, 0.069568814, 0.0193581091, 1.11409238, 264.275294], "lambda_min": 0.28, "lambda_max": 2.4, "nd_ref": 1.438750, "vd_ref": 94.946025, "source": _OHARA_SRC},
    (1.72916, 54.7): {"name": "S-LAL18", "formula": "sellmeier", "coefficients": [1.50276318, 0.0145462356, 0.430224497, -0.00332784153, 1.3472606, 93.3508342], "lambda_min": 0.28, "lambda_max": 2.4, "nd_ref": 1.729157, "vd_ref": 54.680013, "source": _OHARA_SRC},
    (1.78472, 25.7): {"name": "S-TIH11", "formula": "sellmeier", "coefficients": [1.72677471, 0.0129369958, 0.324568628, 0.0618255245, 2.65816809, 221.904637], "lambda_min": 0.37, "lambda_max": 2.4, "nd_ref": 1.784723, "vd_ref": 25.683446, "source": _OHARA_SRC},
    (1.83481, 42.7): {"name": "S-LAH55V", "formula": "sellmeier", "coefficients": [1.97025325, 0.00991088134, 0.30489414, 0.0383202295, 1.39214665, 97.7785249], "lambda_min": 0.365, "lambda_max": 2.325, "nd_ref": 1.834807, "vd_ref": 42.725324, "source": _OHARA_SRC},
    (1.92286, 18.9): {"name": "S-NPH2", "formula": "sellmeier", "coefficients": [2.0386951, 0.0170796224, 0.437269641, 0.0749254813, 2.96711461, 174.155354], "lambda_min": 0.39, "lambda_max": 2.4, "nd_ref": 1.922860, "vd_ref": 18.896912, "source": _OHARA_SRC},
    (1.48749, 70.2): {"name": "S-FSL5", "formula": "sellmeier", "coefficients": [1.17447043, 0.00841855181, 0.0140056154, -0.0581790767, 1.19272435, 129.599726], "lambda_min": 0.28, "lambda_max": 2.4, "nd_ref": 1.487490, "vd_ref": 70.236252, "source": _OHARA_SRC},
    (1.58913, 61.1): {"name": "S-BAL35", "formula": "sellmeier", "coefficients": [0.941357273, 0.0140333996, 0.546174895, 0.000906635683, 1.16168917, 114.163758], "lambda_min": 0.3, "lambda_max": 2.4, "nd_ref": 1.589130, "vd_ref": 61.135024, "source": _OHARA_SRC},
    (1.88300, 40.8): {"name": "S-LAH58", "formula": "sellmeier", "coefficients": [1.78764964, 0.00847378536, 0.6526356, 0.0313126408, 1.79914564, 132.788001], "lambda_min": 0.32, "lambda_max": 2.4, "nd_ref": 1.882997, "vd_ref": 40.765107, "source": _OHARA_SRC},
    (2.00100, 29.1): {"name": "TAFD55", "formula": "polynomial", "coefficients": [3.8317578, -0.015266397, 2, 0.054573843, -2, 0.0023109346, -4, -4.4476201e-05, -6, 1.6143887e-05, -8], "lambda_min": 0.36501, "lambda_max": 1.01398, "nd_ref": 2.00100, "vd_ref": 29.13, "source": _HOYA_SRC},
    (2.00069, 25.5): {"name": "TAFD40", "formula": "polynomial", "coefficients": [3.8106232, -0.016351565, 2, 0.058801097, -2, 0.0034919026, -4, -0.0001694811, -6, 3.2569333e-05, -8], "lambda_min": 0.36501, "lambda_max": 1.01398, "nd_ref": 2.00069, "vd_ref": 25.46, "source": _HOYA_SRC},
}


def canon_zoom() -> Project:
    """7x zoom of Canon's JP2015094867A, Numerical Example 1: 17-119 mm, F2.8-3.4, image height 14.8 mm, 50 surfaces
    in four groups (groups 2 and 3 move: gaps d18, d26, d29), two conic aspheres (S1, S8), a fluorite element.
    Configurations: wide, middle, tele. Clear apertures: the published effective diameters, with each zoom
    position's vignetting factors (CANON_ZOOM_VIGNETTING) so that its marginal rays just pass.
    Reference wavelength e, as the patent's data (tests/test_reference_designs.py)."""
    from .io.zmx import _model_glass

    custom: dict[str, dict] = {}
    surfaces = [_s(id="obj", label="Object", thickness=None)]
    for i, (r, d, nd, vd, eff) in enumerate(CANON_ZOOM_TABLE, start=1):
        sd = _s(id=f"s{i}", label=f"S{i}", radius=r, thickness=CANON_ZOOM_GAPS[i][0] if d is None else d, semi_diameter=eff / 2, semi_diameter_mode="fixed")
        if nd:
            g = CANON_ZOOM_GLASSES.get((nd, vd))
            if g is None:  # 1.43387 / 95.1: fluorite
                g = _model_glass("FLUORITE", nd, vd)
                g["source"] = "Model glass through the patent's nd 1.43387, vd 95.1 (fluorite)"
            else:
                g = dict(g, family=g["source"].split()[0], category="glass", catalog=g["source"].split()[0])
            custom[g["name"]] = g
            sd["material"] = g["name"]
        if i == 30:
            sd.update(label="S30 stop", is_stop=True)
        if i in CANON_ZOOM_ASPHERES:
            k, a = CANON_ZOOM_ASPHERES[i]
            sd.update(type="even_asphere", conic=k, aspheric=a)
        surfaces.append(sd)
    surfaces.append(_s(id="img", label="Image"))
    sys = OpticalSystem.model_validate(
        {
            "name": "Zoom 17-119 mm F2.8-3.4",
            "surfaces": surfaces,
            "wavelengths": [{"value": 0.4861327}, {"value": 0.546074}, {"value": 0.6562725}],
            "primary_wavelength": 1,
            "field_type": "paraxial_image_height",
            "fields": [{"y": 0.0}, {"y": 10.36}, {"y": 14.8}],
            "aperture": {"type": "image_fnum", "value": CANON_ZOOM_FNO[0]},
            "ray_aiming": "real",
            "multi_config": {
                "names": ["Wide 17 mm", "Middle 51 mm", "Tele 119 mm"],
                "operands": [{"parameter": "thickness", "surface_id": f"s{i}", "values": list(v)} for i, v in CANON_ZOOM_GAPS.items()]
                + [{"parameter": "aperture_value", "values": list(CANON_ZOOM_FNO)}]
                + [{"parameter": key, "field": f, "values": list(v)} for (f, key), v in CANON_ZOOM_VIGNETTING.items()],
            },
        }
    )
    return Project(
        metadata=Metadata(
            name="Zoom 17–119 mm F2.8–3.4 (Canon JP2015094867A)",
            description="Seven-times zoom of Canon's patent application JP2015094867A, Numerical Example 1: 17–119 mm, F2.8–3.4, image height 14.8 mm, "
            "50 surfaces in four groups, two conic aspheres and a fluorite element. Wide, middle and tele are configurations; the published effective "
            "diameters are the clear apertures, with each zoom position's own vignetting factors. Glasses: the OHARA and HOYA catalogue glasses with the patent's nd and νd (refractiveindex.info, CC0), "
            "the fluorite as a model glass. Reference wavelength e (546.07 nm), as in the patent: its focal lengths, pupil and principal-point positions "
            "and group data are reproduced within the rounding of its printed table.",
        ),
        system=sys,
        custom_materials=list(custom.values()),
    )


def hubble() -> Project:
    """Hubble Space Telescope Ritchey-Chretien (nominal pre-launch design): primary R = -11040 mm, k = -1.0022985,
    secondary R = -1358 mm, k = -1.496, separation 4906.071 mm, focus 1500 mm behind the primary, EPD 2400 mm (f/24,
    f = 57.6 m); fields 0, 5 and 10 arcmin at 550 nm (COMSOL Ray Optics tutorial; design values also in M. Lallo,
    Opt. Eng. 51 (2012), arXiv:1203.0002). The image surface radius 604.627 mm is the COMSOL model's
    2 (1/R_s - 1/R_p); the 33 % (diametric) central obscuration of the secondary and its baffles is an
    obscuration of radius 396 mm on a plane at the secondary's position."""
    sys = OpticalSystem.model_validate(
        {
            "name": "Hubble Space Telescope (design)",
            "surfaces": [
                _s(id="obj", label="Object", thickness=None),
                # the secondary and its baffle shadow the incoming beam: 33 % (diametric) central obscuration at the secondary's plane
                _s(id="sh", label="Secondary shadow", radius=None, thickness=4906.071, obscuration=396.0),
                _s(id="pm", label="Primary mirror", radius=-11040.0, conic=-1.0022985, thickness=-4906.071, material="MIRROR", is_stop=True),
                _s(id="sm", label="Secondary mirror", radius=-1358.0, conic=-1.496, thickness=6406.071, material="MIRROR"),
                _s(id="img", label="Focal surface", radius=-604.627),
            ],
            "wavelengths": [{"value": 0.55}],
            "primary_wavelength": 0,
            "fields": [{"y": 0.0}, {"y": 5.0 / 60.0}, {"y": 10.0 / 60.0}],
            "field_type": "angle",
            "aperture": {"type": "epd", "value": 2400.0},
        }
    )
    return Project(
        metadata=Metadata(
            name="Hubble Space Telescope (Ritchey–Chrétien design)",
            description="The nominal pre-launch design of the HST Optical Telescope Assembly: hyperbolic primary (R = −11040 mm, k = −1.0022985) and secondary "
            "(R = −1358 mm, k = −1.496), 4906.071 mm apart, focus 1500 mm behind the primary; f = 57.6 m, f/24, fields 0, 5′ and 10′ at 550 nm, on the curved focal "
            "surface of the COMSOL Ray Optics tutorial (R = 604.6 mm). Free of spherical aberration and coma (Ritchey–Chrétien); the remaining field aberration is "
            "astigmatism. The secondary and its baffles obscure the central 33 % of the pupil diameter (an obscuration on a plane at the secondary). "
            "The as-built primary conic (−1.0139) is not modelled.",
        ),
        system=sys,
    )


# Live-image examples: a design together with a built-in photo, opened in the Live image view. The photos are in
# frontend/public/samples (credits in frontend/public/samples/CREDITS.md); the engine receives them like a user's photo.
def _live_settings(scene: str) -> dict:
    return {"liveimage": {"scene": scene, "zoom": 1, "center": [0, 0], "width": 384, "refine": True}}


def live_eiffel() -> Project:
    """The Eiffel Tower (photo looking up its centre) through the plano-convex N-BK7 singlet opened up to f/5 with a
    +-10 deg field, the image at the paraxial focus: spherical aberration, axial colour and the curved field soften the
    photo and fringe its edges; refocusing or an achromat shows what a corrected lens does."""
    base = singlet()
    d = base.system.model_dump()
    d["name"] = "Simple lens f/5"
    d["aperture"]["value"] = 20.0
    d["fields"] = [{"y": 0.0}, {"y": 5.0}, {"y": 10.0}]
    return Project(
        metadata=Metadata(
            name="Eiffel Tower through a simple lens",
            description="Live-image example: the Eiffel Tower photographed through a single N-BK7 plano-convex lens, f = 100 mm at f/5 with a ±10° field and the "
            "image at the paraxial focus. Spherical aberration, axial colour and field curvature soften the picture and fringe its edges. Try Quick focus, "
            "drag a radius, or compare with the achromat. Photo: Jebulon, CC0 (Wikimedia Commons).",
        ),
        system=OpticalSystem.model_validate(d),
        analysis_settings=_live_settings("eiffel"),
        ui={"open_view": "liveimage"},
    )


def live_pillars() -> Project:
    """Hubble's Pillars of Creation (1995) through the Hubble Space Telescope design: diffraction limited at the
    frame's pixels; zoom in to reach the scale of its point spread function."""
    base = hubble()
    return Project(
        metadata=Metadata(
            name="Pillars of Creation through the Hubble telescope",
            description="Live-image example: Hubble's 1995 image of the Pillars of Creation through the nominal Hubble Space Telescope design (f = 57.6 m, f/24, "
            "33 % central obscuration). Over the ±10′ field the telescope is sharp at these pixels; zoom in to see its point spread function. "
            "Image: NASA, Jeff Hester and Paul Scowen (Arizona State University).",
        ),
        system=base.system,
        analysis_settings=_live_settings("pillars"),
        ui={"open_view": "liveimage"},
    )


# U.S. Patent 7,535,658 (Fujinon, M. Taniyama), Example 1, FIGS. 10 and 11: (R, t, (nd, Vd) or air, K, coefficients
# A1 .. A10 on r^1 .. r^10). The patent's aspheric equation is Z = C h^2 / (1 + sqrt(1 - K C^2 h^2)) + sum A_i h^i, so
# K = 1 + k (the conic constant k = K - 1).
CELL_PHONE_ROWS = [
    (1.962, 1.19, (1.471, 76.6), 2.153, [0, 0, -1.895e-2, 2.426e-2, -5.123e-2, 8.371e-4, 7.850e-3, 4.091e-3, -7.732e-3, -4.265e-3]),
    (33.398, 0.93, None, 40.18, [0, 0, -4.966e-3, -1.434e-2, -6.139e-3, -9.284e-5, 6.438e-3, -5.72e-3, -2.385e-2, 1.108e-2]),
    (-2.182, 0.75, (1.603, 27.5), 2.105, [0, 0, -4.388e-2, -2.555e-2, 5.16e-2, -4.307e-2, -2.831e-2, 3.162e-2, 4.630e-2, -4.877e-2]),
    (-6.367, 0.1, None, 3.382, [0, 0, -1.131e-1, -7.863e-2, 1.094e-1, 6.228e-3, -2.216e-2, -5.89e-3, 4.123e-3, 1.041e-3]),
    (5.794, 0.89, (1.510, 56.2), -221.1, [0, 0, -7.876e-2, 7.02e-2, 5.175e-3, -9.958e-3, -7.322e-3, 6.914e-4, 2.54e-3, -7.65e-4]),
    (9.192, 0.16, None, 0.9331, [0, 0, 9.694e-3, -2.516e-3, -3.606e-3, -2.497e-4, -6.84e-4, -1.414e-4, 2.932e-4, -7.284e-5]),
    (1.674, 0.85, (1.510, 56.2), -7.617, [0, 0, 7.429e-2, -6.933e-2, -5.811e-3, 2.396e-3, 2.100e-3, -3.119e-4, -5.552e-5, 7.969e-6]),
    (1.509, 0.70, None, -2.707, [0, 0, 1.767e-3, -4.652e-2, 1.625e-2, -3.522e-3, -7.106e-4, 3.825e-4, 6.271e-5, -2.631e-5]),
]
# Example 1 as printed: the stop 0.20 mm behind the first vertex (FIG. 10: "-0.20", "the minus sign means the stop is
# located on the image side of the surface S1"), a 0.30 mm cover glass, F/2.8; f = 5.57, bf = 1.53, TL = 6.41, Ih = 3.5.
CELL_PHONE_PATENT = {"stop": -0.20, "cover": 0.30, "fnum": 2.8}
# The ray-optics documentation example "Cell Phone lens" differs from the patent in five places: R5 = 5.694 (5.794),
# A5 of the fifth surface 1.575e-3 (5.175e-3), the stop at the first vertex (0.20 mm behind it), a 0.40 mm cover glass
# (0.30) and f/3.5 (F/2.8). tests/test_reference_designs.py checks the engine against ray-optics' printed numbers with
# that transcription; it is weak off axis (RMS spots 13 to 24 um), the patent design is not.
CELL_PHONE_RAY_OPTICS = {"stop": 0.0, "cover": 0.40, "fnum": 3.5, "r5": 5.694, "a5_s5": 1.575e-3}


def cell_phone_lens(transcription: str = "patent") -> Project:
    """Four-element camera-phone lens of U.S. Patent 7,535,658, Example 1 (FIGS. 10 and 11): f = 5.57 mm, F/2.8, the
    stop 0.20 mm behind the first vertex, eight odd aspheres (coefficients on r^3 .. r^10, conics k = K - 1), a cover
    glass and the image 0.64 mm behind it; model glasses from (nd, Vd) (two-term Cauchy through nd and nF - nC).
    Fields as real image heights 0, 2.47 and 3.5 mm. transcription="ray-optics" gives the ray-optics documentation
    example instead (R5, one coefficient, the stop, the cover glass and the aperture differ; see CELL_PHONE_RAY_OPTICS),
    which tests/test_reference_designs.py compares with ray-optics."""
    from .io.zmx import _model_glass

    if transcription not in ("patent", "ray-optics"):
        raise ValueError("transcription must be 'patent' or 'ray-optics'")
    ro = transcription == "ray-optics"
    v = CELL_PHONE_RAY_OPTICS if ro else CELL_PHONE_PATENT
    custom: dict = {}

    def glass(nd: float, vd: float) -> str:
        name = f"MODEL_{nd:.3f}_{vd:.1f}".replace(".", "_")
        if name not in custom:
            g = _model_glass(name, nd, vd)
            g["source"] = f"Model glass nd = {nd}, Vd = {vd} (U.S. Patent 7,535,658); two-term Cauchy through nd and nF - nC"
            custom[name] = g
        return name

    rows = [list(r) for r in CELL_PHONE_ROWS]
    if ro:
        rows[4][0] = v["r5"]
        rows[4][4] = list(rows[4][4])
        rows[4][4][4] = v["a5_s5"]
    surfaces = [_s(id="obj", label="Object", thickness=None), _s(id="stop", label="Stop", radius=None, thickness=v["stop"], is_stop=True)]
    labels = ["L1 front", "L1 back", "L2 front", "L2 back", "L3 front", "L3 back", "L4 front", "L4 back"]
    for k, (r, t, g, ec, coefs) in enumerate(rows):
        surfaces.append(_s(id=f"c{k + 1}", label=labels[k], type="odd_asphere", radius=r, conic=round(ec - 1.0, 10), thickness=t, material=glass(*g) if g else "AIR", odd_coefficients=list(coefs)))
    surfaces += [
        _s(id="ir1", label="Cover glass front" if not ro else "IR filter front", radius=None, thickness=v["cover"], material=glass(1.516, 64.1)),
        _s(id="ir2", label="Cover glass back" if not ro else "IR filter back", radius=None, thickness=0.64),
        _s(id="img", label="Image"),
    ]
    sys = OpticalSystem.model_validate(
        {
            "name": "Cell phone lens, f/3.5 (ray-optics)" if ro else "Cell phone lens, F/2.8",
            "surfaces": surfaces,
            "wavelengths": [{"value": 0.4861327, "weight": 0.5}, {"value": 0.5875618, "weight": 1.0}, {"value": 0.6562725, "weight": 0.5}],
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}, {"y": 2.4749}, {"y": 3.5}],
            "field_type": "image_height",
            "aperture": {"type": "image_fnum", "value": v["fnum"]},
        }
    )
    if ro:
        meta = Metadata(
            name="Cell phone lens f/3.5 (ray-optics transcription of US 7,535,658)",
            description="The ray-optics documentation example of U.S. Patent 7,535,658: R5, one aspheric coefficient, the stop position, the cover glass and the "
            "aperture differ from the patent's Example 1. Used to check the engine against ray-optics.",
        )
    else:
        meta = Metadata(
            name="Cell phone lens F/2.8 (US 7,535,658)",
            description="Four-element camera-phone objective of U.S. Patent 7,535,658, Example 1 (Fujinon): f = 5.57 mm, F/2.8, image height 3.5 mm "
            "(about ±32°), a glass first lens and three resin lenses, eight odd aspheres (r³ … r¹⁰ terms), the stop 0.20 mm behind the first "
            "vertex, a 0.30 mm cover glass. Glasses as model glasses from the patent's nd and Vd. The patent's conditional values (f1/f, f2/f, f3/f, "
            "bf/TL, TL/2Ih) and its distortion and astigmatism curves are reproduced. A published reference design, not optimised here.",
        )
    return Project(metadata=meta, system=sys, custom_materials=list(custom.values()))


# Fibre examples: a fibre and its mode analysis, opened in the Fibre Modes or Fibre Cross-Section view. The optics is
# a 1:1 relay of two ideal lenses (f = 10 mm, the fibre end at the collimator's front focus) at the fibre's wavelength,
# filled to the fibre's numerical aperture. analysis_settings["fibermodes"] holds the Fibre Modes view's settings
# (wavelength_um null: the system's primary wavelength); analysis_settings["fiber2d"] is the cross-section request.
def fibre_settings(**kw) -> dict:
    base = {"wavelength_um": None, "core_radius_um": 4.1, "spec": "na", "na": 0.12, "n_core": 1.4557, "dn": 0.005, "n_clad": 1.444, "clad_material": "FUSED_SILICA",
            "vector": True, "profile_kind": "step", "alpha": 2.0, "layers": [], "dispersion": False, "disp_min_um": 1.2, "disp_max_um": 1.65, "disp_points": 46}
    base.update(kw)
    return base


def fibre_request(st: dict, system_wavelength_um: float) -> dict:
    """The /wave/fiber_modes request the Fibre Modes view sends for its settings (frontend lib/fibre.ts)."""
    out = {"wavelength_um": st["wavelength_um"] if st.get("wavelength_um") else system_wavelength_um, "core_radius_um": st["core_radius_um"], "vector": st["vector"],
           "profile_kind": st["profile_kind"], "alpha": st["alpha"], "layers": st["layers"]}
    out[st["spec"]] = st[st["spec"]]
    if st.get("clad_material"):
        out["clad_material"] = st["clad_material"]
    else:
        out["n_clad"] = st["n_clad"]
    return out


def _fibre_relay(name: str, lam: float, na: float, field_mm: float) -> OpticalSystem:
    return OpticalSystem.model_validate(
        {
            "name": name,
            "surfaces": [
                _s(id="obj", label="Fibre end", thickness=10.0),
                _s(id="col", label="Collimator (ideal, f = 10 mm)", type="ideal", focal_length=10.0, ideal_object_distance=10.0, thickness=20.0, is_stop=True),
                _s(id="foc", label="Focusing lens (ideal, f = 10 mm)", type="ideal", focal_length=10.0, thickness=10.0),
                _s(id="img", label="Image of the fibre end"),
            ],
            "wavelengths": [{"value": lam}],
            "field_type": "object_height",
            "fields": [{"y": 0.0}, {"y": field_mm}],
            "aperture": {"type": "object_na", "value": na},
        }
    )


def fibre_smf() -> Project:
    """Step-index single-mode fibre: a = 4.1 um, the core 0.0052 above fused silica (Malitson), 1550 nm; exact vector
    modes, LP01 field diameter and effective area, LP11 cut-off and the dispersion (material, waveguide) over
    1.2 to 1.65 um with the zero-dispersion wavelength."""
    return Project(
        metadata=Metadata(
            name="Single-mode step-index fibre (1550 nm)",
            description="Step-index single-mode fibre: core radius 4.1 µm, core index 0.0052 above fused silica, at 1550 nm. Fibre Modes shows the exact "
            "vector modes, the LP01 mode field diameter and effective area, the LP11 cut-off wavelength and the chromatic dispersion from 1.2 to 1.65 µm "
            "(material and waveguide parts, zero-dispersion wavelength).",
        ),
        system=_fibre_relay("Single-mode fibre, 1:1 relay", 1.55, 0.12, 0.004),
        analysis_settings={"fibermodes": fibre_settings(core_radius_um=4.1, spec="dn", dn=0.0052, dispersion=True, disp_min_um=1.2, disp_max_um=1.65, disp_points=46)},
        ui={"open_view": "fibermodes"},
    )


def fibre_graded() -> Project:
    """Graded-index multimode fibre 50/125: parabolic profile (alpha = 2), NA 0.2, 850 nm."""
    return Project(
        metadata=Metadata(
            name="Graded-index multimode fibre 50/125 (850 nm)",
            description="Graded-index multimode fibre: 50 µm core with a parabolic index profile (α = 2) and NA 0.2 over fused silica, at 850 nm. "
            "Fibre Modes lists its LP mode groups (about 340 guided modes), their fields and the LP01 mode field diameter; change α to see the mode groups split.",
        ),
        system=_fibre_relay("Multimode fibre, 1:1 relay", 0.85, 0.2, 0.025),
        analysis_settings={"fibermodes": fibre_settings(core_radius_um=25.0, spec="na", na=0.2, profile_kind="graded", alpha=2.0)},
        ui={"open_view": "fibermodes"},
    )


FIBRE_TRENCH_RINGS = [[4.0, 0.005], [9.0, 0.0], [14.0, -0.005]]


def fibre_trench() -> Project:
    """Trench-assisted single-mode fibre: core a = 4 um (+0.005), inner cladding to 9 um, a -0.005 trench to 14 um."""
    return Project(
        metadata=Metadata(
            name="Trench-assisted single-mode fibre (1550 nm)",
            description="Single-mode fibre with a depressed trench in the cladding: core radius 4 µm (+0.005 over fused silica), inner cladding to 9 µm and a "
            "−0.005 trench from 9 to 14 µm, at 1550 nm. Fibre Modes solves the layered profile exactly and gives its cut-off, field diameter and dispersion; "
            "edit the rings to design your own profile.",
        ),
        system=_fibre_relay("Trench-assisted fibre, 1:1 relay", 1.55, 0.12, 0.004),
        analysis_settings={"fibermodes": fibre_settings(core_radius_um=4.0, profile_kind="layers", layers=[list(x) for x in FIBRE_TRENCH_RINGS], dispersion=True, disp_min_um=1.2, disp_max_um=1.65, disp_points=46)},
        ui={"open_view": "fibermodes"},
    )


# White et al., JOSA B 19, 2322 (2002) (multipole method), as tabulated by Guo et al., Opt. Express 12, 3341 (2004):
# six air holes of 5 um diameter on a 6.75 um pitch in glass of index 1.45 at 1.45 um.
FIBRE_PCF_REFERENCE = {"neff": 1.445395345, "kappa": 3.15e-8}
FIBRE_PCF_REQUEST = {"wavelength_um": None, "n_background": 1.45, "background_material": None,
                     "lattice": {"pitch_um": 6.75, "d_um": 5.0, "rings": 1, "n_hole": 1.0, "hole_material": None, "missing_centre": True},
                     "shapes": [], "window_um": 10.5, "mesh_um": 0.1, "pml_um": 3.0, "polarisation": "x", "count": 4, "n_guess": None, "refine": True}


def fibre_pcf() -> Project:
    """Six-hole microstructured (photonic crystal) fibre: the leaky fundamental mode by the full-vector cross-section
    solver with an absorbing layer and Richardson refinement, against the multipole method's published value."""
    return Project(
        metadata=Metadata(
            name="Six-hole microstructured fibre (1.45 µm)",
            description="Microstructured fibre with one ring of six air holes (diameter 5 µm, pitch 6.75 µm) in glass of index 1.45 at 1.45 µm. "
            "Fibre Cross-Section computes the full-vector fundamental mode, its effective index and its leakage loss through the holes; the published multipole "
            "result is n_eff = 1.445395345 + 3.15·10⁻⁸ i (White et al., JOSA B 19, 2322, 2002).",
        ),
        system=_fibre_relay("Microstructured fibre, 1:1 relay", 1.45, 0.1, 0.004),
        analysis_settings={"fiber2d": dict(FIBRE_PCF_REQUEST, lattice=dict(FIBRE_PCF_REQUEST["lattice"]))},
        ui={"open_view": "fiber2d"},
    )


# Lighting examples: light sources and detectors in free space, opened in the Non-Sequential view with its photometric
# read-outs (illuminance in lux, luminous flux, the colour of the light). The sequential system is free space (no lens:
# the illumination is the subject); analysis_settings["nonseq"] holds the view's settings.
def white_led_spectrum(samples: int = 48, blue: float = 0.25) -> list[dict]:
    """A phosphor-converted white LED: a blue line (450 nm, FWHM 20 nm) and the phosphor band (565 nm, FWHM 110 nm)
    with the given share of the blue line in the radiant power, binned over 400–760 nm (bin integrals of the
    Gaussians by error functions; weights sum to one)."""
    edges = [0.400 + (0.760 - 0.400) * k / samples for k in range(samples + 1)]

    def bins(c: float, fwhm: float) -> list[float]:
        sd = fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
        w = [0.5 * (math.erf((b - c) / (math.sqrt(2.0) * sd)) - math.erf((a - c) / (math.sqrt(2.0) * sd))) for a, b in zip(edges[:-1], edges[1:])]
        t = sum(w)
        return [x / t for x in w]

    w = [blue * x + (1.0 - blue) * y for x, y in zip(bins(0.450, 0.020), bins(0.565, 0.110))]
    return [{"value": round(0.5 * (a + b), 6), "weight": x} for a, b, x in zip(edges[:-1], edges[1:], w)]


def _free_space(name: str, labels: tuple[str, str, str], d1: float, d2: float, lam: list[float], aperture: dict, fields: list[dict], field_type: str, infinite: bool = False) -> OpticalSystem:
    return OpticalSystem.model_validate(
        {
            "name": name,
            "surfaces": [
                _s(id="obj", label=labels[0], thickness=None if infinite else d1),
                _s(id="ref", label=labels[1], thickness=d2, is_stop=True),
                _s(id="img", label=labels[2]),
            ],
            "wavelengths": [{"value": v} for v in lam],
            "field_type": field_type,
            "fields": fields,
            "aperture": aperture,
        }
    )


def _ns_settings(**kw) -> dict:
    base = {"field": 0, "wavelength": None, "rays": 400, "overfill": 1.2, "split": True, "include_system": True, "pixels": 64, "detector_radius": None, "log": False,
            "seed": 1, "imp_target": "none", "imp_rays": 4, "max_seconds": 60, "quantity": "illuminance"}
    base.update(kw)
    return base


LED_HEIGHT_MM = 2000.0
LED_RADIANT_W = 3.0
DESK_RADIUS_MM = 300.0


def led_downlight() -> Project:
    """A white LED (Lambertian, Ø2 mm) 2 m above a 3 m x 3 m work plane, with a Ø600 mm desk on it (a monitor that
    lets the light through): the illuminance in lux, the luminous flux and the colour of the light."""
    z_led = -10.0
    sources = [
        LightSource(id="src-led", name="White LED", placement={"position": [0.0, 0.0, z_led]}, shape="disk", size_x=1.0, angular="lambertian",
                    power_w=LED_RADIANT_W, rays=200000, wavelengths=white_led_spectrum())
    ]
    z_plane = z_led + LED_HEIGHT_MM
    detectors = [
        Detector(id="det-plane", name="Work plane 3 × 3 m", placement={"position": [0.0, 0.0, z_plane]}, shape="rectangle", size_x=3000.0, size_y=3000.0, pixels=31),
        Detector(id="det-desk", name="Desk Ø600 mm", placement={"position": [0.0, 0.0, z_plane - 1.0]}, shape="circle", size_x=DESK_RADIUS_MM, mode="monitor", pixels=24),
    ]
    return Project(
        metadata=Metadata(
            name="LED downlight on a work plane",
            description="Lighting example: a white LED (blue chip and phosphor, 3 W of light, Lambertian) 2 m above a 3 m × 3 m work plane with a Ø600 mm desk. "
            "The Non-Sequential view gives the illuminance map in lux, the luminous flux and average illuminance of each detector, and the colour of the light "
            "(chromaticity, correlated colour temperature) next to the source's own.",
        ),
        system=_free_space("LED and work plane (free space)", ("LED", "Reference plane", "Work plane"), 10.0, LED_HEIGHT_MM - 10.0, [0.45, 0.565], {"type": "object_na", "value": 0.6}, [{"y": 0.0}, {"y": 1.0}], "object_height"),
        sources=sources,
        detectors=detectors,
        analysis_settings={"nonseq": _ns_settings(pixels=31)},
        ui={"open_view": "nonseq"},
    )


# Additive colour mixing: three collimated monochromatic beams of 60 mm x 60 mm (centre (x, y) mm, wavelength um, W)
# overlapping on a 120 mm screen; every edge lies on a 5 mm pixel edge of the screen.
RGB_BEAMS = (("Red 630 nm", (-15.0, 10.0), 0.630, 1.0), ("Green 532 nm", (15.0, 10.0), 0.532, 0.35), ("Blue 465 nm", (0.0, -15.0), 0.465, 1.2))
RGB_BEAM_SIZE_MM = 60.0
RGB_SCREEN_MM = 120.0
RGB_PIXELS = 24


def colour_mixing() -> Project:
    """Red, green and blue beams overlap on a screen: the true-colour map shows additive mixing."""
    sources = [
        LightSource(id=f"src-{k}", name=name, placement={"position": [c[0], c[1], 0.0]}, shape="rectangle", size_x=RGB_BEAM_SIZE_MM, size_y=RGB_BEAM_SIZE_MM,
                    angular="collimated", power_w=pw, rays=60000, wavelengths=[{"value": lam, "weight": 1.0}])
        for k, (name, c, lam, pw) in enumerate(RGB_BEAMS)
    ]
    detectors = [Detector(id="det-screen", name="Screen 120 × 120 mm", placement={"position": [0.0, 0.0, 100.0]}, shape="rectangle", size_x=RGB_SCREEN_MM, size_y=RGB_SCREEN_MM, pixels=RGB_PIXELS)]
    return Project(
        metadata=Metadata(
            name="Additive colour mixing (RGB)",
            description="Colour example: red (630 nm), green (532 nm) and blue (465 nm) beams of 60 mm × 60 mm overlap on a screen. The Non-Sequential view's "
            "true-colour map shows the single colours, their pairwise mixtures and the triple overlap; hover for the chromaticity of each pixel.",
        ),
        system=_free_space("RGB beams and screen (free space)", ("Beams", "Beam plane", "Screen"), 0.0, 100.0, [b[2] for b in RGB_BEAMS], {"type": "epd", "value": 90.0}, [{"y": 0.0}], "angle", infinite=True),
        sources=sources,
        detectors=detectors,
        analysis_settings={"nonseq": _ns_settings(pixels=RGB_PIXELS, quantity="colour")},
        ui={"open_view": "nonseq"},
    )


# Grating examples (RCWA): a grating and its diffraction efficiencies, opened in the Grating (RCWA) view. The
# optics is a 1:1 relay of ideal lenses at the grating's wavelength (the grating is the subject).
# analysis_settings["rcwa"] is the view's request (/wave/rcwa).
def _grating_project(name: str, description: str, lam: float, request: dict) -> Project:
    return Project(
        metadata=Metadata(name=name, description=description),
        system=_fibre_relay(f"{name}: 1:1 relay", lam, 0.05, 0.5),
        analysis_settings={"rcwa": request},
        ui={"open_view": "rcwa"},
    )


GRATING_LAMBDA_UM = 0.633


def binary_phase_depth_um(lam: float = GRATING_LAMBDA_UM) -> float:
    """Depth of a fused-silica binary grating with a half-wave (pi) phase step in air: lambda / (2 (n - 1))."""
    from .materials import MaterialLibrary

    return lam / (2.0 * (MaterialLibrary().index("FUSED_SILICA", lam) - 1.0))


def binary_grating() -> Project:
    """Binary phase grating beam splitter: fused-silica lines, 50 % fill, pi phase depth, period 20 um at 633 nm."""
    h = round(binary_phase_depth_um(), 5)
    req = {"wavelength_um": GRATING_LAMBDA_UM, "period_um": 20.0, "theta_deg": 0.0, "phi_deg": 0.0, "polarisation": "TE", "harmonics": 60,
           "incident": {"n": 1.0, "k": 0.0, "material": None}, "substrate": {"n": None, "k": 0.0, "material": "FUSED_SILICA"},
           "layers": [{"kind": "lamellar", "thickness_um": h, "fill": 0.5, "fill_top": 0.5, "fill_bottom": 0.5, "slices": 10,
                       "ridge": {"n": None, "k": 0.0, "material": "FUSED_SILICA"}, "groove": {"n": 1.0, "k": 0.0, "material": None}}],
           "sweep": None}
    return _grating_project(
        "Binary phase grating beam splitter (633 nm)",
        "Grating example: fused-silica lines (period 20 µm, 50 % fill) etched to a half-wave phase step. The zeroth order vanishes and ±1 carry about "
        "40 % each (4/π² in scalar theory); the Grating view gives every order's efficiency and angle by rigorous coupled-wave analysis.",
        GRATING_LAMBDA_UM, req)


def waveplate_grating() -> Project:
    """Form-birefringent quarter-wave plate: a fused-silica grating far below the wavelength (period 0.2 um)."""
    req = {"wavelength_um": GRATING_LAMBDA_UM, "period_um": 0.2, "theta_deg": 0.0, "phi_deg": 0.0, "polarisation": "unpolarised", "harmonics": 20,
           "incident": {"n": 1.0, "k": 0.0, "material": None}, "substrate": {"n": None, "k": 0.0, "material": "FUSED_SILICA"},
           "layers": [{"kind": "lamellar", "thickness_um": 1.9, "fill": 0.5, "fill_top": 0.5, "fill_bottom": 0.5, "slices": 10,
                       "ridge": {"n": None, "k": 0.0, "material": "FUSED_SILICA"}, "groove": {"n": 1.0, "k": 0.0, "material": None}}],
           "sweep": {"kind": "wavelength", "start": 0.5, "stop": 0.8, "points": 31, "orders": [0]}}
    return _grating_project(
        "Form-birefringent quarter-wave plate",
        "Grating example: fused-silica lines 0.1 µm wide on a 0.2 µm period, 1.9 µm deep. Only the zeroth order propagates and the structure behaves as a "
        "birefringent layer: about 90° of retardance between TE and TM at 633 nm. Shrink the period to see it approach effective-medium theory.",
        GRATING_LAMBDA_UM, req)


GMR_PERIOD_UM = 0.45


def gmr_filter() -> Project:
    """Guided-mode resonance filter: a shallow grating on a high-index waveguide layer reflects a narrow band completely."""
    req = {"wavelength_um": 0.7314, "period_um": GMR_PERIOD_UM, "theta_deg": 0.0, "phi_deg": 0.0, "polarisation": "TE", "harmonics": 25,
           "incident": {"n": 1.0, "k": 0.0, "material": None}, "substrate": {"n": None, "k": 0.0, "material": "FUSED_SILICA"},
           "layers": [{"kind": "lamellar", "thickness_um": 0.05, "fill": 0.5, "fill_top": 0.5, "fill_bottom": 0.5, "slices": 10,
                       "ridge": {"n": 2.0, "k": 0.0, "material": None}, "groove": {"n": 1.0, "k": 0.0, "material": None}},
                      {"kind": "uniform", "thickness_um": 0.12, "fill": 0.5, "fill_top": 0.5, "fill_bottom": 0.5, "slices": 10,
                       "ridge": {"n": 2.0, "k": 0.0, "material": None}, "groove": None}],
           "sweep": {"kind": "wavelength", "start": 0.70, "stop": 0.78, "points": 81, "orders": [0]}}
    return _grating_project(
        "Guided-mode resonance filter",
        "Grating example: a 50 nm deep grating (period 0.45 µm) on a 120 nm layer of index 2.0 over fused silica. Near 731 nm the light couples into "
        "the guided mode of the layer and is reflected completely in a narrow band; the wavelength sweep shows the resonance.",
        0.7314, req)


# ------------------------------------------------------------------ crossed gratings and metasurfaces (wave/rcwa2d.py)
_AIR = {"n": 1.0, "k": 0.0, "material": None}
_FS = {"n": None, "k": 0.0, "material": "FUSED_SILICA"}


def _pattern(thickness: float, background: dict, ridge: dict, shapes: list[dict]) -> dict:
    return {"kind": "pattern", "thickness_um": thickness, "fill": 0.5, "fill_top": 0.5, "fill_bottom": 0.5, "slices": 10,
            "ridge": ridge, "groove": background, "shapes": shapes}


def _square(cx: float, cy: float, a: float, medium: dict | None = None) -> dict:
    return {"kind": "rectangle", "cx_um": cx, "cy_um": cy, "a_um": a, "b_um": a, "angle_deg": 0.0, "medium": medium}


FANOUT_PERIOD_UM = 20.0


def fanout_grating() -> Project:
    """Checkerboard phase grating: fused-silica squares of half the period, half-wave deep, a 2 x 2 spot fan-out."""
    L = FANOUT_PERIOD_UM
    req = {"wavelength_um": GRATING_LAMBDA_UM, "period_um": L, "period_y_um": L, "theta_deg": 0.0, "phi_deg": 0.0, "polarisation": "TE",
           "harmonics": 10, "harmonics_y": 10, "incident": dict(_AIR), "substrate": dict(_FS),
           "layers": [_pattern(round(binary_phase_depth_um(), 5), dict(_AIR), dict(_FS), [_square(0.25 * L, 0.25 * L, 0.5 * L), _square(0.75 * L, 0.75 * L, 0.5 * L)])],
           "sweep": None}
    return _grating_project(
        "Checkerboard fan-out grating (2 × 2 spots)",
        "Crossed grating example: a checkerboard of fused-silica squares (period 20 µm) etched to a half-wave phase step. Its transmission is the "
        "product of two binary gratings, so the light goes into the four orders (±1, ±1), each 16/π⁴ ≈ 16.4 % of the transmitted power in scalar "
        "theory; the zeroth order and the axes (±1, 0), (0, ±1) stay dark.",
        GRATING_LAMBDA_UM, req)


AR_PERIOD_UM = 0.16


def checkerboard_ar_depth_um(lam: float = GRATING_LAMBDA_UM) -> float:
    """Quarter-wave depth of the checkerboard layer: its effective index is sqrt(n) (Dykhne: eps_eff = sqrt(eps1 eps2) = n)."""
    from .materials import MaterialLibrary

    return lam / (4.0 * MaterialLibrary().index("FUSED_SILICA", lam) ** 0.5)


def checkerboard_ar() -> Project:
    """Subwavelength checkerboard of fused silica and air on fused silica: an antireflection layer of index sqrt(n)."""
    L = AR_PERIOD_UM
    req = {"wavelength_um": GRATING_LAMBDA_UM, "period_um": L, "period_y_um": L, "theta_deg": 0.0, "phi_deg": 0.0, "polarisation": "TE",
           "harmonics": 6, "harmonics_y": 6, "incident": dict(_AIR), "substrate": dict(_FS),
           "layers": [_pattern(round(checkerboard_ar_depth_um(), 5), dict(_AIR), dict(_FS), [_square(0.25 * L, 0.25 * L, 0.5 * L), _square(0.75 * L, 0.75 * L, 0.5 * L)])],
           "sweep": {"kind": "wavelength", "start": 0.45, "stop": 0.9, "points": 31, "orders": [0], "orders_2d": [[0, 0]]}}
    return _grating_project(
        "Subwavelength checkerboard antireflection",
        "Metasurface example: a checkerboard of fused silica and air with a period of 0.16 µm, far below the wavelength, on fused silica. Such a "
        "checkerboard behaves as a layer of permittivity √(ε₁ε₂) (Dykhne), here exactly n, i.e. index √n: the ideal single-layer antireflection "
        "coating. At a quarter-wave depth the reflectance at 633 nm drops from 3.5 % to below 10⁻⁴.",
        GRATING_LAMBDA_UM, req)


PHC_PERIOD_UM = 1.1
PHC_HOLE_UM = 0.49


def phc_mirror() -> Project:
    """Photonic-crystal membrane: a square lattice of square holes in a 0.344 um film of index 2.0, a resonant reflector near 1.55 um.
    (Square holes: Li's factorisation is exact for axis-aligned edges, so the resonance converges faster than with round holes.)"""
    L = PHC_PERIOD_UM
    req = {"wavelength_um": 1.5493, "period_um": L, "period_y_um": L, "theta_deg": 0.0, "phi_deg": 0.0, "polarisation": "TE",
           "harmonics": 8, "harmonics_y": 8, "incident": dict(_AIR), "substrate": dict(_AIR),
           "layers": [_pattern(0.344, {"n": 2.0, "k": 0.0, "material": None}, dict(_AIR),
                               [_square(0.5 * L, 0.5 * L, PHC_HOLE_UM)])],
           "sweep": {"kind": "wavelength", "start": 1.45, "stop": 1.65, "points": 61, "orders": [0], "orders_2d": [[0, 0]]}}
    return _grating_project(
        "Photonic-crystal membrane reflector",
        "Metasurface example: a 344 nm membrane of index 2.0 (silicon nitride) with a square lattice of 0.49 µm square holes, period 1.1 µm, in air. A "
        "guided resonance near 1.55 µm reflects the light completely, for either polarisation; next to it the membrane transmits completely. "
        "The wavelength sweep shows the Fano line.",
        1.5493, req)


# ------------------------------------------------------------------ plasmonics (wave/fdtd.py, dispersive metals)
SPP_GOLD_NK = (0.197, 3.09)  # gold near 633 nm
SPP_WAVELENGTH_UM = 0.633


def spp_gold() -> Project:
    """Surface plasmon on gold: the FDTD launches it at its own profile and fits its propagation constant."""
    n, k = SPP_GOLD_NK
    req = {"wavelength_um": SPP_WAVELENGTH_UM, "polarization": "p", "size_z_um": 4.0, "size_y_um": 1.9, "n_background": 1.0, "source": "spp",
           "spp_y_um": -0.6, "waist_um": 2.0, "focus_z_um": 0.0, "focus_y_um": 0.0, "tilt_deg": 0.0, "points_per_wavelength": 30, "reference": False,
           "shapes": [{"kind": "rectangle", "name": "Gold", "n": n, "k": k, "z0": -50.0, "z1": 50.0, "y0": -5.0, "y1": -0.6}]}
    return Project(
        metadata=Metadata(name="Surface plasmon on gold (633 nm)", description=(
            "Plasmonics example: gold (n + ik = 0.197 + 3.09i, a typical value at 633 nm) below air. The FDTD treats the metal as a dispersive "
            "medium (a Drude current fitted to its permittivity at the wavelength), launches the surface plasmon at its own profile and fits its "
            "propagation constant along the interface: run it to compare n_eff = 1.0560 + 0.0078i and the 6.5 µm propagation length with "
            "k_spp = k0 √(ε_m / (ε_m + 1)).")),
        system=_fibre_relay("Surface plasmon on gold: 1:1 relay", SPP_WAVELENGTH_UM, 0.05, 0.5),
        analysis_settings={"fdtd": req},
        ui={"open_view": "fdtd"},
    )


# ------------------------------------------------------------------ interferometric testing (analysis/interferometry.py)
PARA_R_MM = 1200.0
PARA_D_MM = 150.0
HENE_UM = 0.6328


def paraboloid_test() -> Project:
    """A 150 mm f/4 paraboloid tested at its centre of curvature (Twyman-Green): the classic null-test failure."""
    sys = OpticalSystem.model_validate(
        {
            "name": "Paraboloid at its centre of curvature",
            "surfaces": [
                _s(id="obj", label="Interferometer focus (at the centre of curvature)", thickness=PARA_R_MM),
                _s(id="pm", label="Paraboloid", radius=-PARA_R_MM, conic=-1.0, thickness=-PARA_R_MM, material="MIRROR", is_stop=True, semi_diameter=PARA_D_MM / 2),
                _s(id="img", label="Return focus"),
            ],
            "wavelengths": [{"value": HENE_UM}],
            "fields": [{"y": 0.0}],
            "aperture": {"type": "epd", "value": PARA_D_MM},
        }
    )
    return Project(
        metadata=Metadata(name="Paraboloid tested at its centre of curvature", description=(
            "Interferometry example: a 150 mm f/4 paraboloid (R = 1200 mm) in a Twyman-Green interferometer whose focus sits at the mirror's centre "
            "of curvature, at the HeNe line. A sphere would be a null test with no fringes; the paraboloid departs from it by r⁴/(4R³) in the "
            "double-pass wavefront, about 7.2 waves at the edge, seen as circular fringes. Phase shifting recovers the wavefront from four frames.")),
        system=sys,
        analysis_settings={"interferogram": {"field": 0, "wavelength": 0, "grid": 256, "passes": 1, "tilt_x": 0.0, "tilt_y": 0.0, "visibility": 1.0, "phase_steps": 4}},
        ui={"open_view": "interferogram"},
    )


# ------------------------------------------------------------------ spectrometers (analysis/spectrometer.py)
SPECTRO_F_MM = 100.0
SPECTRO_LINES = 600.0


def grating_spectrograph() -> Project:
    """Transmission grating spectrograph with ideal (aberration-free) collimator and camera."""
    f = SPECTRO_F_MM
    sys = OpticalSystem.model_validate(
        {
            "name": "Grating spectrograph",
            "surfaces": [
                _s(id="obj", label="Slit", thickness=f),
                {"id": "col", "type": "ideal", "label": "Collimator (ideal, f = 100 mm)", "focal_length": f, "thickness": 10.0, "is_stop": True},
                _s(id="gr", label="Transmission grating 600 lines/mm", radius=None, thickness=10.0, grating_frequency=SPECTRO_LINES, diffraction_order=1),
                {"id": "cam", "type": "ideal", "label": "Camera (ideal, f = 100 mm)", "focal_length": f, "thickness": f},
                _s(id="img", label="Detector"),
            ],
            "wavelengths": [{"value": 0.45}, {"value": 0.55}, {"value": 0.65}],
            "primary_wavelength": 1,
            "fields": [{"y": 0.0}],
            "aperture": {"type": "epd", "value": 20.0},
        }
    )
    return Project(
        metadata=Metadata(name="Grating spectrograph (ideal optics)", description=(
            "Spectrometer example: a slit point, an f = 100 mm collimator, a 600 lines/mm transmission grating and an f = 100 mm camera, the lenses "
            "ideal. Each wavelength images at y = f tan(asin(m λ G)): 28.0 mm at 450 nm to 42.4 mm at 650 nm, a linear dispersion of 0.067 to 0.077 "
            "mm/nm. The 20 mm beam covers 12000 grating lines, a diffraction-limited resolving power of 12000 (0.046 nm at 550 nm). Replace a lens "
            "with a real one to see the geometric resolution.")),
        system=sys,
        analysis_settings={"spectrometer": {"field": 0, "wl_min_um": 0.45, "wl_max_um": 0.65, "points": 41, "density": 6}},
        ui={"open_view": "spectrometer"},
    )


SAMPLES = {
    "live-eiffel": ("Eiffel Tower through a simple lens", live_eiffel),
    "live-pillars": ("Pillars of Creation through the Hubble telescope", live_pillars),
    "achromat": ("Achromatic doublet (optimized)", lambda: achromat(True)),
    "achromat-start": ("Achromatic doublet (thin-lens start)", lambda: achromat(False)),
    "cooke-triplet": ("Cooke triplet (optimized)", lambda: cooke_triplet(True)),
    "cooke-triplet-start": ("Cooke triplet (rough start)", lambda: cooke_triplet(False)),
    "double-gauss": ("Double Gauss f/1.7, 100 mm (US 2,784,643)", double_gauss),
    "geiser-triplet": ("Geiser triplet f/4, 50 mm (Sasián / ray-optics)", geiser_triplet),
    "petzval": ("Petzval f/2.4, 100 mm with field flattener (Kidger)", petzval_kidger),
    "cell-phone-lens": ("Cell phone lens F/2.8 (US 7,535,658)", cell_phone_lens),
    "singlet": ("Plano-convex singlet", singlet),
    "spherical-mirror": ("Spherical mirror", spherical_mirror),
    "fold-mirror": ("Folded singlet (coordinate breaks)", fold_mirror),
    "achromat-two-conjugates": ("Achromat at two conjugates (multi-configuration)", achromat_two_conjugates),
    "hubble": ("Hubble Space Telescope (Ritchey–Chrétien design)", hubble),
    "canon-zoom": ("Zoom 17–119 mm F2.8–3.4 (Canon JP2015094867A)", canon_zoom),
    "fibre-smf": ("Single-mode step-index fibre (1550 nm)", fibre_smf),
    "fibre-graded": ("Graded-index multimode fibre 50/125", fibre_graded),
    "fibre-trench": ("Trench-assisted single-mode fibre", fibre_trench),
    "fibre-pcf": ("Six-hole microstructured fibre", fibre_pcf),
    "led-downlight": ("LED downlight on a work plane", led_downlight),
    "colour-mixing": ("Additive colour mixing (RGB)", colour_mixing),
    "binary-grating": ("Binary phase grating beam splitter", binary_grating),
    "waveplate-grating": ("Form-birefringent quarter-wave plate", waveplate_grating),
    "gmr-filter": ("Guided-mode resonance filter", gmr_filter),
    "fanout-grating": ("Checkerboard fan-out grating (2 × 2 spots)", fanout_grating),
    "checkerboard-ar": ("Subwavelength checkerboard antireflection", checkerboard_ar),
    "phc-mirror": ("Photonic-crystal membrane reflector", phc_mirror),
    "spp-gold": ("Surface plasmon on gold (633 nm)", spp_gold),
    "paraboloid-test": ("Paraboloid tested at its centre of curvature", paraboloid_test),
    "grating-spectrograph": ("Grating spectrograph (ideal optics)", grating_spectrograph),
}


# Start-screen groups (ids are translated in the UI)
SAMPLE_CATEGORIES = {
    "live-eiffel": "liveimage",
    "live-pillars": "liveimage",
    "achromat": "imaging",
    "achromat-start": "imaging",
    "cooke-triplet": "imaging",
    "cooke-triplet-start": "imaging",
    "double-gauss": "imaging",
    "geiser-triplet": "imaging",
    "petzval": "imaging",
    "cell-phone-lens": "imaging",
    "hubble": "mirrors",
    "singlet": "imaging",
    "spherical-mirror": "mirrors",
    "fold-mirror": "mirrors",
    "achromat-two-conjugates": "multiconfig",
    "canon-zoom": "multiconfig",
    "fibre-smf": "fibre",
    "fibre-graded": "fibre",
    "fibre-trench": "fibre",
    "fibre-pcf": "fibre",
    "led-downlight": "lighting",
    "colour-mixing": "lighting",
    "binary-grating": "gratings",
    "waveplate-grating": "gratings",
    "gmr-filter": "gratings",
    "fanout-grating": "gratings",
    "checkerboard-ar": "gratings",
    "phc-mirror": "gratings",
    "spp-gold": "gratings",
    "paraboloid-test": "mirrors",
    "grating-spectrograph": "gratings",
}
CATEGORY_ORDER = ("liveimage", "imaging", "fibre", "lighting", "gratings", "mirrors", "multiconfig")


def _outline(p: Project) -> dict | None:
    """Thumbnail outline of a sample (drawing data from the layout trace); None if it cannot be traced."""
    from .analysis.outline import system_outline
    from .system import compile_system

    try:
        return system_outline(compile_system(p.system, p.custom_materials))
    except Exception:  # pragma: no cover - a sample that fails to compile still lists without a picture
        return None


@lru_cache(maxsize=1)
def _listing() -> tuple[dict, ...]:
    out = []
    for k, (name, make) in SAMPLES.items():
        p = make()
        out.append({"id": k, "name": name, "description": p.metadata.description, "category": SAMPLE_CATEGORIES.get(k, "imaging"), "outline": _outline(p)})
    return tuple(out)


def list_samples() -> list[dict]:
    """Sample designs with their start-screen group and a thumbnail outline (frozen designs: computed once)."""
    return [dict(x) for x in _listing()]


def get_sample(sample_id: str) -> Project:
    if sample_id not in SAMPLES:
        raise KeyError(sample_id)
    return SAMPLES[sample_id][1]()
