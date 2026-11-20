"""A shared process pool for CPU-heavy engine jobs (the design space map, the optimiser's Jacobians; the advisor can
use it too).

The ray tracer is NumPy code that holds the GIL for much of its time, so threads do not run candidates in
parallel; separate processes do. The pool uses the spawn start method on every platform (the only one on
Windows), so a worker imports the engine itself and shares no state with the server.

* Workers: ``OPTICORE_WORKERS`` or the number of CPUs minus one (at least one). The pool starts on the first
  job and shuts down after ``IDLE_SECONDS`` without one, so an idle server holds no worker processes.
* Cancel: every job takes a slot in a shared byte array that the workers inherit when they start. A
  task gets its slot number; ``flag(slot)`` is an event-like object whose ``is_set()`` reads that byte (no
  inter-process call), so the optimiser's per-evaluation cancel check stays cheap.
"""

from __future__ import annotations

import concurrent.futures as cf
import multiprocessing as mp
import os
import threading

SLOTS = 256
IDLE_SECONDS = 300.0

_lock = threading.Lock()
_ctx = mp.get_context("spawn")
_pool: cf.ProcessPoolExecutor | None = None
_flags = None  # RawArray('b', SLOTS): 1 = cancel the job in this slot
_free: list[int] = []
_users = 0
_timer: threading.Timer | None = None
_worker_flags = None  # the array inside a worker process


def worker_count() -> int:
    env = os.environ.get("OPTICORE_WORKERS", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, (os.cpu_count() or 2) - 1)


def _init(flags) -> None:  # runs in each worker process
    global _worker_flags
    _worker_flags = flags
    # one BLAS thread per worker: the pool is the parallelism
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(k, "1")


class Flag:
    """Event-like view of a job's cancel byte (``is_set``/``set``), usable in the server and in workers."""

    def __init__(self, slot: int, flags=None):
        self.slot = slot
        self._flags = flags

    def _arr(self):
        return self._flags if self._flags is not None else _worker_flags

    def is_set(self) -> bool:
        a = self._arr()
        return bool(a[self.slot]) if a is not None else False

    def set(self) -> None:
        a = self._arr()
        if a is not None:
            a[self.slot] = 1

    def clear(self) -> None:
        a = self._arr()
        if a is not None:
            a[self.slot] = 0


def in_worker() -> bool:
    """True inside a pool worker process (a nested pool there would multiply the processes)."""
    return _worker_flags is not None


def idle() -> bool:
    """No job holds the pool now (a new job's tasks would not queue behind another's)."""
    with _lock:
        return _users == 0


def flag(slot: int) -> Flag:
    """The cancel flag of a slot, inside a worker task."""
    return Flag(slot)


def acquire() -> tuple[cf.ProcessPoolExecutor, Flag]:
    """The pool (started if needed) and a fresh cancel flag for one job; pair with ``release``."""
    global _pool, _flags, _free, _users, _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        if _pool is None:
            _flags = _ctx.RawArray("b", SLOTS)
            _free = list(range(SLOTS))
            _pool = cf.ProcessPoolExecutor(max_workers=worker_count(), mp_context=_ctx, initializer=_init, initargs=(_flags,))
        if not _free:
            raise RuntimeError("Too many engine jobs at once")
        slot = _free.pop(0)
        _flags[slot] = 0
        _users += 1
        return _pool, Flag(slot, _flags)


def release(f: Flag, broken: bool = False) -> None:
    """End a job: free its slot; a broken pool is replaced on the next job; an idle pool shuts down later."""
    global _users, _timer, _pool
    with _lock:
        _users = max(0, _users - 1)
        if _flags is not None and f.slot not in _free:
            _flags[f.slot] = 0
            _free.append(f.slot)
        if broken and _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None
        if _users == 0 and _pool is not None:
            _timer = threading.Timer(IDLE_SECONDS, _shutdown_if_idle)
            _timer.daemon = True
            _timer.start()


def _shutdown_if_idle() -> None:
    global _pool, _timer
    with _lock:
        _timer = None
        if _users == 0 and _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


def shutdown() -> None:
    """Stop the pool now (tests, server shutdown)."""
    global _pool, _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        if _pool is not None:
            _pool.shutdown(wait=True, cancel_futures=True)
            _pool = None
