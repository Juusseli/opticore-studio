"""Finite-difference Jacobians of the merit residuals on the shared process pool (workers.py).

Every iteration of the least-squares solver needs one residual evaluation per variable for its Jacobian. They are
independent, so they run in the pool's worker processes, in one task per worker (a chunk of columns each).

* Workers: each keeps a MeritFunction per run (token), so a system is compiled once per worker. Its warm starts
  (real ray aiming, image-height fields) carry over between Jacobians.
* Steps (``fd_steps``): h = step · max(1, |x|) with the sign of x (+ at 0), adjusted to the bounds like SciPy's
  one-sided scheme: reversed where x + h would leave either bound and fits on the other side, else to the farther
  bound. The serial Jacobian (engine.py, both constraint modes) uses the same steps, so the two agree to the
  warm-start tolerances: real ray aiming about 1e-14 mm, image-height fields 1e-12 mm. (SciPy 1.18's own
  '2-point' steps step · |x| with ``diff_step``, which is not step · max(1, |x|) for |x| < 1, and about
  1.5e-8 · max(1, |x|) without it.)
* Budget: a Jacobian starts only when all its columns fit the evaluation budget (``reserve``), as the serial one.
* When it is used (``maybe``): at least ``MIN_VARIABLES`` variables, at least two workers, a first evaluation of at
  least ``MIN_SECONDS``, and no other job on the pool (a design-space map would queue ahead of the columns). Never
  inside a pool worker: the design-space map and the stock-lens build run their candidates' optimisations there,
  already one per core.
  ``OPTICORE_PARALLEL_JACOBIAN=0`` turns it off, ``force`` turns it on for any size (tests).
* On a 12-thread machine the cell-phone lens (14 variables, about 0.17 s per evaluation) optimises 2.4 times
  faster (70 s -> 29 s for 400 evaluations, the first run including the pool's start), to the same merit.
* Every column counts as an evaluation (budget, progress, best point). Cancel is checked while the columns run,
  and set on the job's pool flag so the workers stop between columns.
* With the pool, the solver's other evaluations (its trial steps) run in a worker too: the optimisation then
  does not share the server process's interpreter lock with the requests of the views that follow its preview
  (in the UI those requests slow main-process evaluations about tenfold).
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import pickle
import time
import uuid

import numpy as np

from .. import workers

MIN_VARIABLES = 3
MIN_SECONDS = 0.02

_MF: dict = {}  # in a worker: token -> MeritFunction


def _columns(token: str, payload: bytes, xs: list, slot: int) -> list:
    """Worker task: residual vectors at the points xs (None for a point that fails or after a cancel)."""
    from .merit import MeritFunction

    mf = _MF.get(token)
    if mf is None:
        system, spec, custom, offsets, ns, split = pickle.loads(payload)
        mf = MeritFunction(system, spec, custom, offsets, ns=ns, split=split)
        if len(_MF) >= 4:
            _MF.clear()
        _MF[token] = mf
    stop = workers.flag(slot)
    out = []
    for x in xs:
        if stop.is_set():
            out.append(None)
            continue
        try:
            r, _ = mf.evaluate(np.asarray(x, dtype=float))
            out.append(r)
        except Exception:  # noqa: BLE001 - the main process evaluates this column itself
            out.append(None)
    return out


def fd_steps(x: np.ndarray, lo: np.ndarray, hi: np.ndarray, step: float) -> np.ndarray:
    """Forward-difference steps (module notes) adjusted to the bounds like SciPy's one-sided scheme
    (_numdiff._adjust_scheme_to_bounds): a step that would leave either bound is reversed when it fits on the other
    side, otherwise it goes to the farther bound."""
    x, lo, hi = (np.asarray(a, dtype=float) for a in (x, lo, hi))
    sign = np.where(x >= 0, 1.0, -1.0)
    h = step * sign * np.maximum(1.0, np.abs(x))
    lower, upper = x - lo, hi - x
    violated = (x + h < lo) | (x + h > hi)
    fitting = np.abs(h) <= np.maximum(lower, upper)
    h = np.where(violated & fitting, -h, h)
    h = np.where(~fitting, np.where(upper >= lower, upper, -lower), h)
    return (x + h) - x  # exactly representable steps, as SciPy does


def enabled() -> bool:
    return os.environ.get("OPTICORE_PARALLEL_JACOBIAN", "1").strip() not in ("0", "false", "no")


class ParallelJacobian:
    """jac(x) for scipy.optimize.least_squares. ``residual(x)`` evaluates in the main process (used for f0 when it
    is not cached and for columns a worker could not deliver); ``on_column(x, r)`` records an evaluation;
    ``check()`` raises to stop (cancel, pause, budget); ``reserve(n)`` (optional) raises when n more evaluations do
    not fit the budget, so a Jacobian is started only when all its columns fit (as the serial one, engine.py)."""

    def __init__(self, system, spec, custom_materials, index_offsets, ns, lo, hi, step, residual, on_column, check, cancelled, split=False, reserve=None):
        self.payload = pickle.dumps((system, spec, list(custom_materials), dict(index_offsets or {}), ns, bool(split)))
        self.token = uuid.uuid4().hex
        self.lo, self.hi, self.step = np.asarray(lo, float), np.asarray(hi, float), float(step)
        self.residual, self.on_column, self.check, self.cancelled = residual, on_column, check, cancelled
        self.reserve = reserve
        self.pool, self.flag = workers.acquire()
        self.n_workers = workers.worker_count()
        self.cache: dict[bytes, np.ndarray] = {}
        self.columns = 0
        self.seconds = 0.0

    def remember(self, x: np.ndarray, r: np.ndarray) -> None:
        """Keep the residuals of the latest points (the solver asks for the Jacobian where it last evaluated)."""
        if len(self.cache) > 8:
            self.cache.clear()
        self.cache[np.asarray(x, dtype=float).tobytes()] = np.asarray(r, dtype=float)

    def steps(self, x: np.ndarray) -> np.ndarray:
        return fd_steps(x, self.lo, self.hi, self.step)

    def run(self, points: list[np.ndarray]) -> list:
        """Residual vectors at the points, from the workers (None where a worker could not deliver one)."""
        if not points:
            return []
        chunks = [list(range(k, len(points), self.n_workers)) for k in range(min(self.n_workers, len(points)))]
        futs = {self.pool.submit(_columns, self.token, self.payload, [points[i] for i in c], self.flag.slot): c for c in chunks}
        out: list = [None] * len(points)
        pending = set(futs)
        try:
            while pending:
                done, pending = cf.wait(pending, timeout=0.05)
                for fu in done:
                    try:
                        res = fu.result()
                    except Exception:  # noqa: BLE001 - a broken worker: the main process does these points
                        res = [None] * len(futs[fu])
                    for i, r in zip(futs[fu], res):
                        out[i] = r
                if self.cancelled():
                    self.flag.set()
        finally:
            for fu in pending:
                fu.cancel()
            self.flag.clear()
        return out

    def __call__(self, x, *args, **kwargs) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        f0 = self.cache.get(x.tobytes())
        if f0 is None:
            f0 = np.asarray(self.residual(x), dtype=float)
        self.check()
        if self.reserve is not None:
            self.reserve(len(x))
        t0 = time.perf_counter()
        dx = self.steps(x)
        points = []
        for i in range(len(x)):
            xi = x.copy()
            xi[i] += dx[i]
            points.append(xi)
        cols = self.run(points)
        J = np.empty((len(f0), len(x)))
        for i, xi in enumerate(points):
            r = cols[i]
            if r is None or len(r) != len(f0):
                self.check()
                r = np.asarray(self.residual(xi), dtype=float)
            else:
                self.on_column(xi, r)
            J[:, i] = (r - f0) / dx[i]
        self.columns += len(points)
        self.seconds += time.perf_counter() - t0
        return J

    def close(self) -> None:
        workers.release(self.flag)


def maybe(nvar: int, first_eval_seconds: float):
    """True when a parallel Jacobian pays (module notes). ``OPTICORE_PARALLEL_JACOBIAN=force`` skips the size and
    time thresholds (tests)."""
    if not enabled() or workers.worker_count() < 2 or workers.in_worker():
        return False  # inside a worker (design-space and stock-lens candidates run there) the run stays serial
    if os.environ.get("OPTICORE_PARALLEL_JACOBIAN", "").strip() == "force":
        return nvar >= 1
    if nvar < MIN_VARIABLES or first_eval_seconds < MIN_SECONDS:
        return False
    return workers.idle()
