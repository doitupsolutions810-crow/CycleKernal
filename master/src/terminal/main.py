"""
Terminal / Sandbox Runtime — CycleKernel Master
Accepts artifacts from the orchestrator, writes them to the shared volume,
and executes them inside a controlled subprocess (sandbox).
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
import os
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ck.terminal")

ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", "/artifacts"))
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CycleKernel Terminal Runtime", version="4.0.0")


class ExecuteRequest(BaseModel):
    filename: str
    content: str
    command: Optional[str] = None
    timeout_sec: int = 15


class ExecuteResponse(BaseModel):
    filename: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timestamp: str


@app.get("/health")
async def health():
    return {"status": "terminal-online", "artifact_root": str(ARTIFACT_ROOT)}


@app.post("/v1/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest):
    """
    Write the artifact and run it under a timeout.
    In a hardened deployment this would use gVisor / Firecracker / nested Docker.
    """
    if ".." in req.filename or req.filename.startswith("/"):
        raise HTTPException(400, "invalid filename")

    target = ARTIFACT_ROOT / req.filename
    target.write_text(req.content, encoding="utf-8")
    logger.info(f"Artifact written: {target}")

    cmd = req.command or f"python {target}"
    started = datetime.utcnow()

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ARTIFACT_ROOT),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=req.timeout_sec)
            exit_code = proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout, stderr = b"", b"TIMEOUT"
            exit_code = 124
    except Exception as e:
        raise HTTPException(500, f"execution failed: {e}")

    duration = int((datetime.utcnow() - started).total_seconds() * 1000)
    return ExecuteResponse(
        filename=req.filename,
        exit_code=exit_code,
        stdout=stdout.decode(errors="replace")[:8000],
        stderr=stderr.decode(errors="replace")[:4000],
        duration_ms=duration,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/v1/artifacts")
async def list_artifacts():
    files = []
    for p in ARTIFACT_ROOT.iterdir():
        if p.is_file():
            files.append({"name": p.name, "size": p.stat().st_size})
    return {"artifacts": files}
