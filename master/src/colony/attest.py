"""
Attested Runners
================
Only execute artifacts that present a known manifest with matching content hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ck.attest")


class AttestationError(Exception):
    pass


@dataclass
class AttestedArtifact:
    manifest_path: str
    root: str
    entry: str
    file_hashes: Dict[str, str]  # relative path → sha256
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    job_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "root": self.root,
            "entry": self.entry,
            "file_hashes": self.file_hashes,
            "registered_at": self.registered_at,
            "job_id": self.job_id,
        }


class AttestationRegistry:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or Path("/tmp/ck-colony/attestation.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: Dict[str, AttestedArtifact] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in data.items():
                self._items[k] = AttestedArtifact(**v)
        except Exception as e:
            logger.warning("attest load failed: %s", e)

    def _save(self) -> None:
        payload = {k: v.to_dict() for k, v in self._items.items()}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def hash_file(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    def register_manifest(
        self,
        manifest_path: str,
        job_id: Optional[str] = None,
    ) -> AttestedArtifact:
        mp = Path(manifest_path)
        if not mp.exists():
            raise AttestationError(f"manifest not found: {manifest_path}")
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        root = Path(manifest["root"])
        entry = manifest.get("entry") or ""
        file_hashes: Dict[str, str] = {}
        for f in manifest.get("files") or []:
            rel = f.get("relative") or Path(f.get("path", "")).name
            expected = f.get("sha256")
            target = root / rel
            if not target.exists():
                raise AttestationError(f"missing file in manifest: {rel}")
            actual = self.hash_file(target)
            if expected and actual != expected:
                raise AttestationError(
                    f"hash mismatch for {rel}: expected {expected[:12]}… got {actual[:12]}…"
                )
            file_hashes[rel] = actual
        art = AttestedArtifact(
            manifest_path=str(mp),
            root=str(root),
            entry=entry,
            file_hashes=file_hashes,
            job_id=job_id,
        )
        key = hashlib.sha256(
            (art.root + art.entry + json.dumps(file_hashes, sort_keys=True)).encode()
        ).hexdigest()[:16]
        self._items[key] = art
        self._save()
        logger.info("attested key=%s root=%s files=%d", key, art.root, len(file_hashes))
        return art

    def verify(self, root: str, entry: str) -> AttestedArtifact:
        root_p = Path(root)
        entry_p = root_p / entry
        if not entry_p.exists():
            raise AttestationError(f"entry missing: {entry_p}")
        # find matching registration
        for art in self._items.values():
            if art.root == str(root_p) and art.entry == entry:
                # re-hash all registered files
                for rel, expected in art.file_hashes.items():
                    actual = self.hash_file(root_p / rel)
                    if actual != expected:
                        raise AttestationError(
                            f"tamper detected on {rel}: {actual[:12]}≠{expected[:12]}"
                        )
                return art
        raise AttestationError(f"not attested: root={root} entry={entry}")

    def list(self) -> List[Dict[str, Any]]:
        return [{"key": k, **v.to_dict()} for k, v in self._items.items()]


class AttestedRunner:
    """Execute only after attestation verify; capture stdout/stderr."""

    def __init__(self, registry: Optional[AttestationRegistry] = None):
        self.registry = registry or AttestationRegistry()

    def run(
        self,
        root: str,
        entry: str,
        timeout_sec: int = 30,
        python: str = "python3",
    ) -> Dict[str, Any]:
        try:
            art = self.registry.verify(root, entry)
        except AttestationError as e:
            return {"success": False, "error": str(e), "attested": False}
        cmd = [python, str(Path(root) / entry)]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-2000:],
                "duration_ms": int((time.time() - started) * 1000),
                "attested": True,
                "artifact": art.to_dict(),
                "command": cmd,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "timeout",
                "attested": True,
                "duration_ms": int((time.time() - started) * 1000),
            }
        except AttestationError as e:
            return {"success": False, "error": str(e), "attested": False}
