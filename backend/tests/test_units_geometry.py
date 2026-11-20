import math

import numpy as np
import pytest

from opticore.geometry import Frame, rot_x, rot_y, rot_z
from opticore.units import UnitError, convert_length, deg_to_rad, length_to_mm, rad_to_deg, wavelength_to_um


def test_length_conversions():
    assert length_to_mm(1, "in") == 25.4
    assert convert_length(1, "m", "mm") == 1000
    assert convert_length(250, "um", "mm") == 0.25
    assert convert_length(convert_length(3.7, "cm", "in"), "in", "cm") == pytest.approx(3.7, rel=1e-15)
    assert wavelength_to_um(587.5618, "nm") == 0.5875618  # correctly rounded, not 0.58756179999
    assert length_to_mm(250, "um") == 0.25
    assert convert_length(0.25, "mm", "um") == 250.0
    with pytest.raises(UnitError):
        length_to_mm(1, "furlong")


def test_angle_conversions():
    assert deg_to_rad(180) == pytest.approx(math.pi)
    assert rad_to_deg(deg_to_rad(33.3)) == pytest.approx(33.3, rel=1e-15)


@pytest.mark.parametrize("R", [rot_x(0.3), rot_y(-1.1), rot_z(2.0), rot_x(0.2) @ rot_y(0.5) @ rot_z(-0.7)])
def test_rotations_orthonormal(R):
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-14)
    assert np.linalg.det(R) == pytest.approx(1.0)


def test_right_handed_rotation():
    # +90 deg about x maps +y to +z
    assert np.allclose(rot_x(math.pi / 2) @ [0, 1, 0], [0, 0, 1], atol=1e-15)
    assert np.allclose(rot_y(math.pi / 2) @ [0, 0, 1], [1, 0, 0], atol=1e-15)
    assert np.allclose(rot_z(math.pi / 2) @ [1, 0, 0], [0, 1, 0], atol=1e-15)


def test_coordinate_break_inverse():
    f0 = Frame(np.array([1.0, -2.0, 3.0]), rot_y(0.3))
    f1 = f0.coordinate_break(0.5, -1.2, 12.0, -7.0, 33.0, order=0)
    f2 = f1.coordinate_break(-0.5, 1.2, -12.0, 7.0, -33.0, order=1)
    assert np.allclose(f2.origin, f0.origin, atol=1e-13)
    assert np.allclose(f2.matrix, f0.matrix, atol=1e-13)


def test_frame_point_roundtrip(rng):
    f = Frame(np.array([3.0, 1.0, -2.0]), rot_x(0.4) @ rot_z(1.3))
    P = rng.normal(size=(10, 3))
    assert np.allclose(f.to_global_points(f.to_local_points(P)), P, atol=1e-13)
    D = rng.normal(size=(10, 3))
    assert np.allclose(f.to_global_dirs(f.to_local_dirs(D)), D, atol=1e-13)
