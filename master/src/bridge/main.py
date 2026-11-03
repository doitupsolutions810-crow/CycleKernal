"""Dev entrypoint for the master tree.

The running image is the repo ``src/bridge`` service. ``master/docker-compose.yml``
builds that context so this file is not what the container executes. From a
checkout, ``uvicorn main:app`` in this directory loads the same app: real relay
intake, ``/events``, and ``/v1/feedback``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CANONICAL = Path(__file__).resolve().parents[3] / "src" / "bridge" / "main.py"
if not _CANONICAL.is_file():
    raise RuntimeError(
        f"Canonical bridge is missing at {_CANONICAL}. "
        "Build the image from src/bridge, which is what master/docker-compose.yml does."
    )

_BRIDGE_DIR = str(_CANONICAL.parent)
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

_spec = importlib.util.spec_from_file_location("ck_bridge_canonical", _CANONICAL)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Cannot load canonical bridge from {_CANONICAL}")
_module = importlib.util.module_from_spec(_spec)
sys.modules["ck_bridge_canonical"] = _module
_spec.loader.exec_module(_module)

app = _module.app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)
