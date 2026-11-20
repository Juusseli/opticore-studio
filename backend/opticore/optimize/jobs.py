"""Background optimisation jobs with progress polling, pause and cancel."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..jsonutil import jsonable
from ..model import OpticalSystem
from .engine import Control, Progress, optimize
from .merit import OptimizationSpec


@dataclass
class Job:
    id: str
    state: str = "queued"  # queued | running | paused | finished | cancelled | failed
    progress: Progress = field(default_factory=Progress)
    control: Control = field(default_factory=Control)
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    thread: threading.Thread | None = None


class JobManager:
    def __init__(self, max_jobs: int = 32):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.max_jobs = max_jobs

    def start(self, system: OpticalSystem, spec: OptimizationSpec, custom_materials=(), ns=None) -> Job:
        job = Job(id=uuid.uuid4().hex[:16])

        def run():
            job.state = "running"
            try:
                job.result = jsonable(optimize(system, spec, custom_materials, job.progress, job.control, ns=ns))
                job.state = "cancelled" if job.result["status"] == "cancelled" else "finished"
            except Exception as exc:  # report to client, never crash the server
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = "failed"
                traceback.print_exc()

        job.thread = threading.Thread(target=run, daemon=True, name=f"opt-{job.id}")
        with self._lock:
            self._prune()
            self._jobs[job.id] = job
        job.thread.start()
        return job

    def _prune(self):
        if len(self._jobs) < self.max_jobs:
            return
        done = sorted((j for j in self._jobs.values() if j.state in ("finished", "cancelled", "failed")), key=lambda j: j.created)
        for j in done[: len(self._jobs) - self.max_jobs + 1]:
            self._jobs.pop(j.id, None)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job.control.cancel.set()
        job.control.pause.clear()
        return True

    def pause(self, job_id: str, paused: bool) -> bool:
        job = self.get(job_id)
        if not job or job.state not in ("running", "paused"):
            return False
        if paused:
            job.control.pause.set()
            job.state = "paused"
        else:
            job.control.pause.clear()
            job.state = "running"
        return True

    def snapshot(self, job: Job, history_points: int = 400) -> dict[str, Any]:
        p = job.progress
        hist = p.history
        if len(hist) > history_points:
            step = len(hist) / history_points
            hist = [hist[int(i * step)] for i in range(history_points)] + [hist[-1]]
        return jsonable(
            {
                "id": job.id,
                "state": job.state,
                "phase": p.phase,
                "evaluations": p.evaluations,
                "initial_merit": p.initial,
                "current_merit": p.current,
                "best_merit": p.best,
                "best_values": p.best_x.tolist() if p.best_x is not None else None,
                "best_materials": p.best_materials,
                "constraints": p.constraints,
                "unmet": p.unmet,
                "history": hist,
                "elapsed_s": time.time() - p.started,
                "error": job.error,
                "result": job.result if job.state in ("finished", "cancelled") else None,
            }
        )
