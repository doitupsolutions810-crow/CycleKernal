"""
Server Hosting Sub-Agent
========================
Hosts sandboxed HTTP runtimes for generated artifacts.
Prefers stdlib http.server / uvicorn-style entrypoints bound to localhost.
Tracks PIDs under CK_ARTIFACT_ROOT for later teardown.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import AgentResult, BaseAgent

logger = logging.getLogger("ck.server")

ARTIFACT_ROOT = Path(os.environ.get("CK_ARTIFACT_ROOT", "/tmp/ck-artifacts"))
RUNTIME_DIR = ARTIFACT_ROOT / "runtimes"
DEFAULT_HOST = os.environ.get("CK_SERVER_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CK_SERVER_PORT", "8765"))


class ServerHostAgent(BaseAgent):
    name = "server"
    role = "sandboxed local server hosting for artifact runtimes"

    async def run(self, task: Dict[str, Any]) -> AgentResult:
        started = datetime.utcnow()
        mood = await self.current_mood()
        action: str = (task.get("action") or "start").lower()

        if action == "stop":
            return self._wrap(True, self._stop(task), mood, started)
        if action == "status":
            return self._wrap(True, self._status(task), mood, started)
        return self._wrap(True, await self._start(task, mood), mood, started)

    async def _start(self, task: Dict[str, Any], mood: Dict[str, Any]) -> Dict[str, Any]:
        name: str = task.get("name") or "ck-runtime"
        host: str = task.get("host") or DEFAULT_HOST
        port: int = int(task.get("port") or DEFAULT_PORT)
        artifact_root: Optional[str] = task.get("artifact_root")
        entry: Optional[str] = task.get("entry")
        mode: str = task.get("mode") or "static"  # static | app

        if not artifact_root and task.get("manifest"):
            artifact_root = task["manifest"].get("root")
            entry = entry or task["manifest"].get("entry")

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        run_dir = RUNTIME_DIR / name
        run_dir.mkdir(parents=True, exist_ok=True)

        # Generate a tiny host app if none provided
        if mode == "app" and artifact_root and entry:
            app_code = textwrap.dedent(f'''\
                """CK sandboxed app host — imports artifact entry as best-effort."""
                import runpy, pathlib
                p = pathlib.Path({str(Path(artifact_root) / entry)!r})
                if p.exists():
                    runpy.run_path(str(p), run_name="__not_main__")
                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
                class H(BaseHTTPRequestHandler):
                    def do_GET(self):
                        body = b'{{"status":"ok","service":"{name}"}}'
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    def log_message(self, *a):
                        pass
                ThreadingHTTPServer(("{host}", {port}), H).serve_forever()
                ''')
            app_path = run_dir / "host_app.py"
            app_path.write_text(app_code, encoding="utf-8")
            cmd = [sys.executable, str(app_path)]
            cwd = str(run_dir)
        else:
            # Static file server over artifact root or runtime dir
            serve_root = artifact_root or str(run_dir)
            # seed index if empty
            root_path = Path(serve_root)
            root_path.mkdir(parents=True, exist_ok=True)
            index = root_path / "index.html"
            if not index.exists():
                index.write_text(
                    f"<html><body><h1>CycleKernel sandbox</h1>"
                    f"<p>{name}</p><p>mood={mood.get('mood')}</p></body></html>",
                    encoding="utf-8",
                )
            cmd = [sys.executable, "-m", "http.server", str(port), "--bind", host]
            cwd = serve_root

        log_path = run_dir / "server.log"
        pid_path = run_dir / "server.pid"
        meta_path = run_dir / "runtime.json"

        # Stop existing if any
        self._stop({"name": name})

        log_f = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        meta = {
            "name": name,
            "pid": proc.pid,
            "host": host,
            "port": port,
            "url": f"http://{host}:{port}/",
            "cwd": cwd,
            "cmd": cmd,
            "mode": mode,
            "started_at": datetime.utcnow().isoformat(),
            "mood": mood.get("mood"),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        time.sleep(0.3)
        alive = proc.poll() is None
        meta["alive"] = alive
        logger.info("Server started name=%s pid=%s url=%s alive=%s", name, proc.pid, meta["url"], alive)
        return meta

    def _stop(self, task: Dict[str, Any]) -> Dict[str, Any]:
        name: str = task.get("name") or "ck-runtime"
        run_dir = RUNTIME_DIR / name
        pid_path = run_dir / "server.pid"
        stopped = False
        pid = None
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                stopped = True
            except Exception as e:
                logger.warning("stop failed pid=%s: %s", pid, e)
            try:
                pid_path.unlink(missing_ok=True)
            except Exception:
                pass
        return {"name": name, "stopped": stopped, "pid": pid}

    def _status(self, task: Dict[str, Any]) -> Dict[str, Any]:
        name: str = task.get("name") or "ck-runtime"
        run_dir = RUNTIME_DIR / name
        meta_path = run_dir / "runtime.json"
        pid_path = run_dir / "server.pid"
        meta: Dict[str, Any] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        alive = False
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                os.kill(pid, 0)
                alive = True
            except Exception:
                alive = False
        meta["alive"] = alive
        # list all runtimes
        all_rt: List[str] = []
        if RUNTIME_DIR.exists():
            all_rt = [p.name for p in RUNTIME_DIR.iterdir() if p.is_dir()]
        return {"name": name, "runtime": meta, "runtimes": all_rt}
