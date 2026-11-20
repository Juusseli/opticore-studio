"""Background wave-optics runs (FDTD, fibre cross-sections: progress, cancel), kept in memory like the optimisation jobs."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..jsonutil import jsonable
from .fdtd import Cancelled, Spec, check_size, run
from .fdtd_bor import run_bor


@dataclass
class FdtdJob:
    id: str
    state: str = "queued"  # queued | running | finished | failed | cancelled
    progress: float = 0.0
    created: float = field(default_factory=time.time)
    started: float | None = None
    result: Any = None
    error: str | None = None
    control: dict = field(default_factory=dict)


class FdtdJobs:
    def __init__(self, max_jobs: int = 8):
        self._jobs: dict[str, FdtdJob] = {}
        self._lock = threading.Lock()
        self.max_jobs = max_jobs

    def start(self, spec: Spec) -> FdtdJob:
        check_size(spec)  # size errors are raised synchronously (FdtdError)
        solver = run_bor if spec.geometry == "axisymmetric" else run
        return self.start_fn(lambda progress, control: solver(spec, progress=progress, control=control))

    def start_fn(self, fn) -> FdtdJob:
        """Run fn(progress, control) in the background (any wave computation: FDTD, fibre cross-sections)."""
        job = FdtdJob(id=uuid.uuid4().hex[:16])

        def work():
            job.state = "running"
            job.started = time.time()
            try:
                job.result = jsonable(fn(lambda f: setattr(job, "progress", f), job.control))
                job.state = "finished"
                job.progress = 1.0
            except Cancelled:
                job.state = "cancelled"
            except Exception as exc:  # reported to the client
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = "failed"

        with self._lock:
            done = sorted((j for j in self._jobs.values() if j.state in ("finished", "failed", "cancelled")), key=lambda j: j.created)
            for j in done[: max(0, len(self._jobs) - self.max_jobs + 1)]:
                self._jobs.pop(j.id, None)
            self._jobs[job.id] = job
        threading.Thread(target=work, daemon=True, name=f"fdtd-{job.id}").start()
        return job

    def get(self, job_id: str) -> FdtdJob | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        j = self._jobs.get(job_id)
        if not j or j.state not in ("queued", "running"):
            return False
        j.control["cancel"] = True
        return True

    def snapshot(self, j: FdtdJob) -> dict:
        elapsed = (time.time() - j.started) if j.started else 0.0
        eta = elapsed * (1 - j.progress) / j.progress if 0 < j.progress < 1 else None
        return {"id": j.id, "state": j.state, "progress": j.progress, "elapsed_s": elapsed, "eta_s": eta, "error": j.error, "result": j.result if j.state == "finished" else None}
