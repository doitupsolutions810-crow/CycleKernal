"""
Job Graph Runtime
=================
Persists sandbox pipeline runs, step lineage, retries, and artifact links.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class JobStep:
    id: str
    agent: str
    status: str = JobStatus.PENDING.value
    attempt: int = 0
    max_retries: int = 2
    input: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    artifact_root: Optional[str] = None
    manifest_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Job:
    id: str
    goal: str
    status: str = JobStatus.PENDING.value
    steps: List[JobStep] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    lineage: List[str] = field(default_factory=list)  # prior job ids
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lineage": self.lineage,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Job":
        steps = [JobStep(**s) for s in d.get("steps") or []]
        return cls(
            id=d["id"],
            goal=d.get("goal", ""),
            status=d.get("status", JobStatus.PENDING.value),
            steps=steps,
            created_at=d.get("created_at") or datetime.utcnow().isoformat(),
            updated_at=d.get("updated_at") or datetime.utcnow().isoformat(),
            lineage=list(d.get("lineage") or []),
            meta=dict(d.get("meta") or {}),
        )


class JobStore:
    """JSON-file backed job store (simple, durable enough for colony local state)."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root or Path(__import__("os").environ.get("CK_COLONY_DATA", "/tmp/ck-colony")) / "jobs")
        self.root.mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.json"
        if not self._index.exists():
            self._index.write_text("[]", encoding="utf-8")

    def _path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def _load_index(self) -> List[str]:
        try:
            return json.loads(self._index.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_index(self, ids: List[str]) -> None:
        # newest first, unique
        seen = set()
        ordered: List[str] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                ordered.append(i)
        self._index.write_text(json.dumps(ordered[:500], indent=2), encoding="utf-8")

    def save(self, job: Job) -> Job:
        job.updated_at = datetime.utcnow().isoformat()
        self._path(job.id).write_text(
            json.dumps(job.to_dict(), indent=2), encoding="utf-8"
        )
        ids = self._load_index()
        if job.id in ids:
            ids.remove(job.id)
        ids.insert(0, job.id)
        self._save_index(ids)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        p = self._path(job_id)
        if not p.exists():
            return None
        return Job.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def list(self, limit: int = 50) -> List[Job]:
        out: List[Job] = []
        for jid in self._load_index()[:limit]:
            j = self.get(jid)
            if j:
                out.append(j)
        return out


class JobGraph:
    """
    Builds and runs the standard colony graph:
      reasoning → coding → artifact → container → server
    with retries and lineage.
    """

    DEFAULT_CHAIN = ["reasoning", "coding", "artifact", "container", "server"]

    def __init__(self, store: Optional[JobStore] = None):
        self.store = store or JobStore()

    def create(
        self,
        goal: str,
        chain: Optional[List[str]] = None,
        lineage: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        require_approval: bool = False,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            goal=goal,
            status=JobStatus.WAITING_APPROVAL.value
            if require_approval
            else JobStatus.PENDING.value,
            lineage=list(lineage or []),
            meta=dict(meta or {}),
        )
        for agent in chain or self.DEFAULT_CHAIN:
            job.steps.append(
                JobStep(
                    id=uuid.uuid4().hex[:8],
                    agent=agent,
                    max_retries=2,
                    input={"goal": goal} if agent in ("reasoning", "coding") else {},
                )
            )
        return self.store.save(job)

    async def run(
        self,
        job_id: str,
        bridge_url: str = "http://cognitive-bridge:8090",
        host_server: bool = True,
        port: int = 8765,
    ) -> Job:
        from agents.spawn import spawn

        job = self.store.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status == JobStatus.WAITING_APPROVAL.value:
            return job

        job.status = JobStatus.RUNNING.value
        self.store.save(job)

        prior: Dict[str, Any] = {"goal": job.goal}
        failed = False
        for step in job.steps:
            step.status = JobStatus.RUNNING.value
            step.started_at = datetime.utcnow().isoformat()
            self.store.save(job)

            task = dict(step.input)
            task.setdefault("goal", job.goal)
            if prior.get("manifest"):
                task["manifest"] = prior["manifest"]
                task["artifact_root"] = prior.get("artifact_root")
                task["entry"] = prior.get("entry")
            if step.agent == "server":
                task.setdefault("action", "start")
                task.setdefault("name", f"job-{job.id}")
                task.setdefault("port", port)
                task.setdefault("mode", "static")
                if not host_server:
                    step.status = JobStatus.SUCCEEDED.value
                    step.output = {"skipped": True}
                    step.finished_at = datetime.utcnow().isoformat()
                    self.store.save(job)
                    continue

            success = False
            last_err = None
            result_out: Dict[str, Any] = {}
            while step.attempt <= step.max_retries and not success:
                step.attempt += 1
                try:
                    result = await spawn(step.agent, task, bridge_url=bridge_url)
                    success = result.success
                    result_out = result.output if isinstance(result.output, dict) else {"value": result.output}
                    if not success:
                        last_err = str(result_out.get("error") or "agent reported failure")
                except Exception as e:
                    last_err = str(e)
                    success = False

            step.finished_at = datetime.utcnow().isoformat()
            if success:
                step.status = JobStatus.SUCCEEDED.value
                step.output = result_out
                if "manifest" in result_out:
                    prior["manifest"] = result_out["manifest"]
                    prior["artifact_root"] = result_out["manifest"].get("root")
                    prior["entry"] = result_out["manifest"].get("entry")
                    step.artifact_root = prior.get("artifact_root")
                    # collect file hashes for attestation
                    files = result_out["manifest"].get("files") or []
                    if files:
                        step.manifest_sha256 = files[0].get("sha256")
                if "artifact_root" in result_out:
                    prior["artifact_root"] = result_out["artifact_root"]
                if result_out.get("dockerfile_path"):
                    prior["container"] = result_out
                if result_out.get("url"):
                    prior["server"] = result_out
            else:
                step.status = JobStatus.FAILED.value
                step.error = last_err
                failed = True
                self.store.save(job)
                break
            self.store.save(job)

        job.status = JobStatus.FAILED.value if failed else JobStatus.SUCCEEDED.value
        job.meta["final"] = {
            k: prior[k] for k in ("artifact_root", "entry", "server", "container") if k in prior
        }
        return self.store.save(job)

    def approve(self, job_id: str) -> Job:
        job = self.store.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status == JobStatus.WAITING_APPROVAL.value:
            job.status = JobStatus.PENDING.value
            self.store.save(job)
        return job
