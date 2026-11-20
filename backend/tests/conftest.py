import numpy as np
import pytest

from opticore.model import OpticalSystem


def make_system(surfaces, **kw) -> OpticalSystem:
    d = {"surfaces": surfaces}
    d.update(kw)
    return OpticalSystem.model_validate(d)


@pytest.fixture
def rng():
    return np.random.default_rng(12345)
