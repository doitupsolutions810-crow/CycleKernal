"""
Colony Control Plane API — jobs, attestation, live fitness, approvals,
automated evolution pipelines, decentralized agent consensus.
Port 8500. Dashboard polls these endpoints. Docs: /docs and docs/API.md
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# monorepo imports
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from colony.jobs import JobGraph, JobStore, JobStatus
from colony.attest import AttestationError, AttestationRegistry, AttestedRunner
from colony.fitness_loop import LiveFitnessLoop
from colony.evolution_pipelines import EvolutionPipelines
from colony.consensus import ConsensusEngine, ConsensusProtocol

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://cognitive-bridge:8090")
CHAT_URL = os.getenv("CHAT_URL", "http://chat:8300")

app = FastAPI(
    title="CycleKernel Colony Control",
    version="5.1.0",
    description=(
        "Unified control plane for CycleKernel Ghost Colony: job graphs, "
        "attested runners, live fitness, automated genome evolution pipelines, "
        "and decentralized agent consensus. Interactive OpenAPI at /docs."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = JobStore()
graph = JobGraph(store)
attest_reg = AttestationRegistry()
runner = AttestedRunner(attest_reg)
fitness = LiveFitnessLoop(bridge_url=BRIDGE_URL)
evo_pipes = EvolutionPipelines(fitness_loop=fitness, bridge_url=BRIDGE_URL)
consensus = ConsensusEngine()

# Pending tool approvals (control surface)
_pending_approvals: Dict[str, Dict[str, Any]] = {}


class CreateJobIn(BaseModel):
    goal: str
    chain: Optional[List[str]] = None
    require_approval: bool = False
    host_server: bool = True
    port: int = 8765


class FeedbackIn(BaseModel):
    success: bool = True
    mood: Optional[str] = None
    tools: Optional[List[str]] = None
    kind: str = "chat"
    meta: Dict[str, Any] = Field(default_factory=dict)


class AttestIn(BaseModel):
    manifest_path: str
    job_id: Optional[str] = None


class RunAttestedIn(BaseModel):
    root: str
    entry: str
    timeout_sec: int = 30


class ApprovalIn(BaseModel):
    id: str
    approve: bool
    reason: Optional[str] = None


@app.get("/health", summary="Control plane liveness", tags=["meta"])
async def health():
    """Return service status counters for jobs, attestation, fitness, consensus, evolution."""
    return {
        "status": "colony-online",
        "version": "5.1.0",
        "jobs": len(store.list(limit=1000)),
        "attested": len(attest_reg.list()),
        "fitness_buffer": len(fitness.buffer),
        "pending_approvals": len(_pending_approvals),
        "consensus_open": len([p for p in consensus.list_proposals(status="open")]),
        "evolution_runs": len(evo_pipes.history),
    }


# ----- Jobs -----

@app.post("/v1/jobs")
async def create_job(body: CreateJobIn):
    job = graph.create(
        goal=body.goal,
        chain=body.chain,
        require_approval=body.require_approval,
        meta={"host_server": body.host_server, "port": body.port},
    )
    return job.to_dict()


@app.get("/v1/jobs")
async def list_jobs(limit: int = 30):
    return {"jobs": [j.to_dict() for j in store.list(limit=limit)]}


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@app.post("/v1/jobs/{job_id}/approve")
async def approve_job(job_id: str):
    try:
        job = graph.approve(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@app.post("/v1/jobs/{job_id}/run")
async def run_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status == JobStatus.WAITING_APPROVAL.value:
        raise HTTPException(402, "job requires approval")
    host = bool(job.meta.get("host_server", True))
    port = int(job.meta.get("port", 8765))
    job = await graph.run(job_id, bridge_url=BRIDGE_URL, host_server=host, port=port)
    fitness.record_job(job.status == JobStatus.SUCCEEDED.value, job.id, {"status": job.status})
    # auto-attest artifact steps
    for step in job.steps:
        if step.agent == "artifact" and step.status == JobStatus.SUCCEEDED.value:
            mp = (step.output or {}).get("manifest_path")
            if mp:
                try:
                    attest_reg.register_manifest(mp, job_id=job.id)
                except AttestationError as e:
                    job.meta["attest_error"] = str(e)
                    store.save(job)
    await fitness.maybe_step_genome()
    return job.to_dict()


# ----- Attestation -----

@app.post("/v1/attest/register")
async def attest_register(body: AttestIn):
    try:
        art = attest_reg.register_manifest(body.manifest_path, job_id=body.job_id)
        return art.to_dict()
    except AttestationError as e:
        raise HTTPException(400, str(e))


@app.get("/v1/attest")
async def attest_list():
    return {"artifacts": attest_reg.list()}


@app.post("/v1/attest/run")
async def attest_run(body: RunAttestedIn):
    result = runner.run(body.root, body.entry, timeout_sec=body.timeout_sec)
    from colony.fitness_loop import OutcomeEvent
    fitness.record(
        OutcomeEvent(
            kind="tool",
            success=bool(result.get("success")),
            tools=["attested_run"],
            meta={"root": body.root, "entry": body.entry},
        )
    )
    if not result.get("attested") and not result.get("success"):
        raise HTTPException(403, result.get("error") or "not attested")
    return result


# ----- Live fitness -----

@app.post("/v1/fitness/feedback")
async def fitness_feedback(body: FeedbackIn):
    if body.kind == "server":
        fitness.record_server(body.success, name=str((body.meta or {}).get("name") or "unknown"), meta=body.meta)
    elif body.kind == "job":
        fitness.record_job(body.success, job_id=str((body.meta or {}).get("job_id") or ""), meta=body.meta)
    else:
        fitness.record_chat(body.success, mood=body.mood, tools=body.tools, meta=body.meta)
    stepped = await fitness.maybe_step_genome()
    return {"ok": True, "snapshot": fitness.snapshot(), "evolved": stepped}


@app.post("/v1/fitness/step")
async def fitness_step():
    return await fitness.maybe_step_genome(force=True)


@app.get("/v1/fitness")
async def fitness_status():
    return fitness.snapshot()


# ----- Control surface: tool / genome approvals -----

@app.get("/v1/approvals")
async def list_approvals():
    return {"pending": list(_pending_approvals.values())}


@app.post("/v1/approvals")
async def submit_approval_request(payload: Dict[str, Any]):
    aid = payload.get("id") or __import__("uuid").uuid4().hex[:10]
    _pending_approvals[aid] = {**payload, "id": aid, "status": "pending"}
    return _pending_approvals[aid]


@app.post("/v1/approvals/decide")
async def decide_approval(body: ApprovalIn):
    item = _pending_approvals.pop(body.id, None)
    if not item:
        raise HTTPException(404, "approval not found")
    item["status"] = "approved" if body.approve else "denied"
    item["reason"] = body.reason
    # Genome promote path
    if body.approve and item.get("type") == "genome_promote":
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{BRIDGE_URL}/v1/genome/evolve", json={"context": item.get("context") or {}})
        except Exception:
            pass
    return item


# ----- Proxy helpers for dashboard -----

@app.get("/v1/proxy/mood")
async def proxy_mood():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{BRIDGE_URL}/v1/current_mood")
            return r.json()
    except Exception as e:
        return {"mood": "neutral", "error": str(e), "traits": [], "explanation": "bridge offline"}


@app.get("/v1/proxy/genome")
async def proxy_genome():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{BRIDGE_URL}/v1/genome")
            return r.json()
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


@app.get("/v1/proxy/bulkheads")
async def proxy_bulkheads():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{CHAT_URL}/v1/bulkheads")
            return r.json()
    except Exception as e:
        return {"error": str(e), "bulkheads": {}}


@app.get("/v1/proxy/circuits")
async def proxy_circuits():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{CHAT_URL}/v1/circuits")
            return r.json()
    except Exception as e:
        return {"error": str(e), "circuits": {}}



# ----- Automated evolution pipelines -----

class MultiObjectiveIn(BaseModel):
    weights: Optional[Dict[str, float]] = None
    generations: int = 4


class PeriodicIn(BaseModel):
    force: bool = False


class JobLineageIn(BaseModel):
    job_ids: Optional[List[str]] = None


@app.post("/v1/evolution/pipelines/batch_feedback", tags=["evolution"], summary="Batch feedback genome step")
async def evo_batch():
    """Flush live fitness buffer and run a hybrid genome evolution step."""
    return (await evo_pipes.run_batch_feedback(force=True)).to_dict()


@app.post("/v1/evolution/pipelines/multi_objective", tags=["evolution"], summary="Multi-objective evolution")
async def evo_multi(body: MultiObjectiveIn = None):
    """Evolve under normalized weights for success / safety / novelty."""
    body = body or MultiObjectiveIn()
    return (await evo_pipes.run_multi_objective(weights=body.weights, generations=body.generations)).to_dict()


@app.post("/v1/evolution/pipelines/speciation", tags=["evolution"], summary="Species genome evolution")
async def evo_species():
    """Maintain ops / research / balanced species with distinct fitness priors."""
    return (await evo_pipes.run_speciation()).to_dict()


@app.post("/v1/evolution/pipelines/job_lineage", tags=["evolution"], summary="Evolve from job outcomes")
async def evo_jobs(body: JobLineageIn = None):
    """Derive fitness from job graph results and evolve the genome."""
    body = body or JobLineageIn()
    if body.job_ids:
        jobs = []
        for jid in body.job_ids:
            j = store.get(jid)
            if j:
                jobs.append(j.to_dict())
    else:
        jobs = [j.to_dict() for j in store.list(limit=20)]
    return (await evo_pipes.run_job_lineage(jobs)).to_dict()


@app.post("/v1/evolution/pipelines/periodic", tags=["evolution"], summary="Periodic evolution tick")
async def evo_periodic(body: PeriodicIn = None):
    """Wall-clock periodic evolution; skips until interval elapses unless force=true."""
    body = body or PeriodicIn()
    return (await evo_pipes.run_periodic(force=body.force)).to_dict()


@app.post("/v1/evolution/pipelines/run_all", tags=["evolution"], summary="Run full evolution suite")
async def evo_all():
    """Run batch_feedback, multi_objective, speciation, job_lineage, and forced periodic."""
    jobs = [j.to_dict() for j in store.list(limit=20)]
    return await evo_pipes.run_all(jobs=jobs)


@app.get("/v1/evolution/pipelines", tags=["evolution"], summary="Evolution pipeline status")
async def evo_status():
    """Species snapshot, recent pipeline history, periodic timer."""
    return evo_pipes.snapshot()


# ----- Decentralized consensus -----

class ProposalIn(BaseModel):
    type: str = Field(..., description="tool_execute | job_approve | genome_promote | chain_select | custom")
    summary: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    protocol: str = Field(default="weighted", description="majority | weighted | unanimous | quorum")
    invited: Optional[List[str]] = None
    quorum: float = 0.5
    auto_vote: bool = False


class VoteIn(BaseModel):
    agent: str
    value: str = Field(..., description="approve | deny | abstain")
    reason: str = ""
    weight: Optional[float] = None


@app.post("/v1/consensus/proposals", tags=["consensus"], summary="Open consensus proposal")
async def consensus_open(body: ProposalIn):
    """Open a proposal. Set auto_vote=true to cast heuristic agent votes and tally."""
    if body.auto_vote:
        mood = {}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                mood = (await client.get(f"{BRIDGE_URL}/v1/current_mood")).json()
        except Exception:
            pass
        p = consensus.decide_with_agents(
            type=body.type,
            summary=body.summary,
            payload=body.payload,
            protocol=body.protocol,
            mood=mood,
            invited=body.invited,
        )
        return p.to_dict()
    p = consensus.open_proposal(
        type=body.type,
        summary=body.summary,
        payload=body.payload,
        protocol=body.protocol,
        invited=body.invited,
        quorum=body.quorum,
    )
    return p.to_dict()


@app.post("/v1/consensus/proposals/{proposal_id}/vote", tags=["consensus"], summary="Cast agent vote")
async def consensus_vote(proposal_id: str, body: VoteIn):
    """Cast or replace a vote; auto-tallies and may close the proposal."""
    try:
        p = consensus.cast_vote(
            proposal_id,
            agent=body.agent,
            value=body.value,
            reason=body.reason,
            weight=body.weight,
        )
        return p.to_dict()
    except KeyError:
        raise HTTPException(404, "proposal not found")
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/v1/consensus/decide", tags=["consensus"], summary="One-shot agent consensus")
async def consensus_decide(body: ProposalIn):
    """Open proposal, cast decentralized heuristic votes, tally, and close."""
    mood = {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            mood = (await client.get(f"{BRIDGE_URL}/v1/current_mood")).json()
    except Exception:
        pass
    p = consensus.decide_with_agents(
        type=body.type,
        summary=body.summary,
        payload=body.payload,
        protocol=body.protocol,
        mood=mood,
        invited=body.invited,
    )
    # Side effects on approval
    if p.status == "approved" and p.type == "genome_promote":
        await evo_pipes.run_batch_feedback(force=True)
    return p.to_dict()


@app.get("/v1/consensus/proposals", tags=["consensus"], summary="List proposals")
async def consensus_list(status: Optional[str] = None):
    """List proposals, optionally filtered by status=open|approved|denied."""
    return {"proposals": consensus.list_proposals(status=status)}


@app.get("/v1/consensus/proposals/{proposal_id}", tags=["consensus"], summary="Get proposal")
async def consensus_get(proposal_id: str):
    p = consensus.proposals.get(proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    return p.to_dict()



# Dashboard static
_DASH = Path(__file__).resolve().parents[2] / "web" / "dashboard"
if _DASH.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_DASH), html=True), name="dashboard")


@app.get("/")
async def root():
    index = _DASH / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"service": "colony", "dashboard": "/dashboard/"}
