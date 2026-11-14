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
import signal
import sys
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ck.terminal")

ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", "/artifacts"))
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CycleKernel Terminal Runtime", version="4.0.0")
MAX_SOURCE_BYTES = 2_000_000
MAX_STDOUT_BYTES = 8_000
MAX_STDERR_BYTES = 4_000


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> bytes:
    """Continuously drain the stream, retaining only a bounded prefix."""
    kept = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            return bytes(kept)
        if len(kept) < cap:
            kept.extend(chunk[:cap - len(kept)])


async def _consume(proc: asyncio.subprocess.Process) -> tuple[bytes, bytes, int]:
    stdout, stderr, code = await asyncio.gather(
        _read_capped(proc.stdout, MAX_STDOUT_BYTES),
        _read_capped(proc.stderr, MAX_STDERR_BYTES),
        proc.wait(),
    )
    return stdout, stderr, code or 0


async def _cleanup_group(proc: asyncio.subprocess.Process) -> None:
    """Terminate the process group, including children of exited shells."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await proc.wait()


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

    root = ARTIFACT_ROOT.resolve()
    if not req.filename.strip() or "\x00" in req.filename:
        raise HTTPException(400, "invalid filename")
    target = (root / req.filename).resolve()
    if target == root or root not in target.parents:
        raise HTTPException(400, "invalid filename")
    if not 1 <= req.timeout_sec <= 120:
        raise HTTPException(422, "timeout_sec must be between 1 and 120")
    if len(req.content.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(413, "artifact source exceeds 2 MB limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    logger.info("Artifact written: %s", target)
    started = datetime.utcnow()

    try:
        kwargs = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str(root),
            "start_new_session": True,
        }
        # The default path never passes a filename through a shell.
        # Explicit shell commands remain privileged and need upstream controls.
        if req.command:
            proc = await asyncio.create_subprocess_shell(req.command, **kwargs)
        else:
            proc = await asyncio.create_subprocess_exec(sys.executable, str(target), **kwargs)
        try:
            try:
                stdout, stderr, exit_code = await asyncio.wait_for(
                    _consume(proc), timeout=req.timeout_sec
                )
            except asyncio.TimeoutError:
                stdout, stderr, exit_code = b"", b"TIMEOUT", 124
        finally:
            # Success, timeout and cancellation all clean up child processes.
            await _cleanup_group(proc)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise HTTPException(500, f"execution failed: {e}") from e
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
