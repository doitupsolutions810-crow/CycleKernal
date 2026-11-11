"""
Artifact Sub-Agent
==================
Packages code/content into durable artifacts under a sandbox-safe path.
Produces manifests suitable for container and server agents.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import AgentResult, BaseAgent

logger = logging.getLogger("ck.artifact")

# Sandbox root — never write outside this tree
ARTIFACT_ROOT = Path(os.environ.get("CK_ARTIFACT_ROOT", "/tmp/ck-artifacts"))


class ArtifactAgent(BaseAgent):
    name = "artifact"
    role = "artifact packaging, manifest generation, sandbox file materialization"

    async def run(self, task: Dict[str, Any]) -> AgentResult:
        started = datetime.utcnow()
        mood = await self.current_mood()

        name: str = task.get("name") or task.get("filename") or "artifact"
        content: Optional[str] = task.get("content")
        language: str = task.get("language", "python")
        files: List[Dict[str, str]] = list(task.get("files") or [])
        goal: str = task.get("goal") or ""

        # If coding output was passed through
        if not content and not files and task.get("code"):
            content = task["code"]
        if not files and content:
            filename = task.get("filename") or (
                f"{name}.py" if language == "python" else f"{name}.txt"
            )
            files = [{"path": filename, "content": content}]

        if not files:
            # Minimal default artifact
            files = [{
                "path": f"{name}.py",
                "content": textwrap.dedent(f'''\
                    """CycleKernel artifact: {name}
                    Goal: {goal[:120]}
                    """
                    def main():
                        print("artifact:{name}")
                        return 0
                    if __name__ == "__main__":
                        raise SystemExit(main())
                    '''),
            }]

        run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        dest = ARTIFACT_ROOT / run_id / name
        dest.mkdir(parents=True, exist_ok=True)

        written: List[Dict[str, Any]] = []
        for f in files:
            rel = f.get("path") or f.get("filename") or "file.txt"
            # path traversal guard
            rel = rel.lstrip("/").replace("..", "_")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data = f.get("content") or ""
            target.write_text(data, encoding="utf-8")
            digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
            written.append({
                "path": str(target),
                "relative": rel,
                "bytes": len(data.encode("utf-8")),
                "sha256": digest,
            })

        manifest = {
            "name": name,
            "run_id": run_id,
            "root": str(dest),
            "files": written,
            "entry": written[0]["relative"] if written else None,
            "language": language,
            "goal": goal,
            "mood": mood.get("mood"),
            "created_at": datetime.utcnow().isoformat(),
        }
        manifest_path = dest / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        output = {
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "artifact_root": str(dest),
            "run_command": f"python {dest / (manifest['entry'] or 'artifact.py')}",
        }
        logger.info("Artifact materialized root=%s files=%d", dest, len(written))
        return self._wrap(True, output, mood, started)
