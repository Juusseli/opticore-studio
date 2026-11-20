"""Coordinate frames and rotations.

A frame is (origin O, rotation matrix M) where the columns of M are the local
x, y, z axes expressed in global coordinates. A local point p maps to the
global point P = O + M p; a global direction D maps to the local d = M^T D.

Rotations are right-handed (positive angle rotates y towards z about x, z
towards x about y and x towards y about z).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


@dataclass(frozen=True)
class Frame:
    origin: np.ndarray
    matrix: np.ndarray

    @staticmethod
    def identity() -> "Frame":
        return Frame(np.zeros(3), np.eye(3))

    def to_local_points(self, P: np.ndarray) -> np.ndarray:
        return (P - self.origin) @ self.matrix

    def to_local_dirs(self, D: np.ndarray) -> np.ndarray:
        return D @ self.matrix

    def to_global_points(self, p: np.ndarray) -> np.ndarray:
        return p @ self.matrix.T + self.origin

    def to_global_dirs(self, d: np.ndarray) -> np.ndarray:
        return d @ self.matrix.T

    def translated_local(self, dz: float) -> "Frame":
        """Frame moved by dz along its own z axis."""
        return Frame(self.origin + dz * self.matrix[:, 2], self.matrix)

    def coordinate_break(
        self,
        decenter_x: float,
        decenter_y: float,
        tilt_x_deg: float,
        tilt_y_deg: float,
        tilt_z_deg: float,
        order: int = 0,
    ) -> "Frame":
        """Apply a coordinate break.

        order 0: decenter (in the current frame), then tilt about x, y', z''.
        order 1: tilt about z, y', x'', then decenter in the tilted frame.
        A break with order 1 and negated parameters exactly undoes an order-0
        break, which is how a tilted element is "returned" to the axis."""
        ax, ay, az = (math.radians(tilt_x_deg), math.radians(tilt_y_deg), math.radians(tilt_z_deg))
        dec = np.array([decenter_x, decenter_y, 0.0])
        if order == 0:
            origin = self.origin + self.matrix @ dec
            matrix = self.matrix @ rot_x(ax) @ rot_y(ay) @ rot_z(az)
        else:
            matrix = self.matrix @ rot_z(az) @ rot_y(ay) @ rot_x(ax)
            origin = self.origin + matrix @ dec
        return Frame(origin, matrix)

    def is_axial(self, tol: float = 1e-12) -> bool:
        """True if the frame lies on the global z axis without tilt."""
        return bool(
            abs(self.origin[0]) < tol
            and abs(self.origin[1]) < tol
            and np.allclose(self.matrix, np.eye(3), atol=tol)
        )
