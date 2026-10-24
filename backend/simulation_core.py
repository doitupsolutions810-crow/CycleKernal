"""
CycleKernel Simulation Core with ChatMemoryBridge Integration
Combines the simulation engine with memory-based chat interactions.
NS fitness is fused into live mood and gates colony promotion.
"""
import hmac
import logging
import os
import time
from datetime import datetime
from threading import Lock

import numpy as np
from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from flask_cors import CORS
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from descent_engine import DescentEngine, entropy_with_stress
from ns_fusion import (colony_genome, fuse_mood, genome_id, fitness_channels, build_fitness_evidence, build_fusion_identity_state, fitness_state_id, promote_decision)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

simulation_cycles = Counter("simulation_cycles_total", "Total simulation cycles executed")
active_civilizations = Gauge("active_civilizations", "Number of active civilizations")
total_attention = Gauge("total_attention", "Total attention across all civilizations")
total_compute = Gauge("total_compute", "Total compute resources")
chat_interactions = Counter("chat_interactions_total", "Total chat interactions processed")
simulation_duration = Histogram("simulation_cycle_duration_seconds", "Time taken for simulation cycles")
promoted_colonists = Gauge("promoted_colonists", "Civilizations promoted by fused NS mood")
great_scale_descent_ticks = Counter("great_scale_descent_ticks_total", "Great Scale descent ticks executed")
great_scale_descent_residual = Gauge("great_scale_descent_stress_residual", "Current Great Scale stress residual", ["universe_id"])
great_scale_descent_x = Gauge("great_scale_descent_x", "Current Great Scale descent coordinate", ["universe_id"])

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")


def civ_template(civ_id):
    faction = np.random.choice(["Truth", "Deception", "Neutral"])
    civ = {
        "id": civ_id,
        "faction": faction,
        "resources": {"attention": 50, "compute": 20, "memory_nodes": 1},
        "belief": {"truth": 0.5, "deception": 0.5},
        "state": "active",
        "promoted": False,
        "ns_fitness": 0.0,
        "mood_dot": 0.5,
        "mood": "neutral",
        "fusion_state_id": "",
        "fitness_evidence": {},
        "created_at": datetime.now().isoformat(),
    }
    civ["genome_id"] = genome_id(f"{civ_id}:{faction}")
    return civ


class Universe:
    def __init__(self, universe_id):
        self.id = universe_id
        self.civilizations = {}
        self.factions = {"Truth": 0, "Deception": 0, "Neutral": 0}
        self.myths = {}
        self.cycle_count = 0
        self.promote_log = []
        self.max_promotion_log = 500
        self.fusion_log = []
        self.max_fusion_log = 500
        # One scheduler-driven Great Scale tick per universe simulation cycle.
        self.descent_engine = DescentEngine(start=1.0, k=0.5)
        self._descent_state_lock = Lock()

    def add_civilization(self, civ_id):
        if civ_id not in self.civilizations:
            civ = civ_template(civ_id)
            self.civilizations[civ_id] = civ
            self.factions[civ["faction"]] += 1
            logger.info(f"Added civilization {civ_id} to universe {self.id}")
            return civ
        return self.civilizations[civ_id]

    def colony_snapshot(self):
        """Return one internally consistent civilization/lineage snapshot."""
        with self._descent_state_lock:
            return self._colony_snapshot_locked()

    def _colony_snapshot_locked(self):
        civs = list(self.civilizations.values())
        promoted = [c for c in civs if c.get("promoted")]
        active = [c for c in civs if c.get("state") in ("active", "promoted")]
        dormant = [c for c in civs if c.get("state") not in ("active", "promoted")]
        held = [c for c in civs if not c.get("promoted") and c.get("state") == "active"]
        genome = colony_genome([c["genome_id"] for c in promoted] or [c["genome_id"] for c in civs])
        mood_dot = sum(c.get("mood_dot", 0.5) for c in civs) / max(len(civs), 1)
        return {
            "active": len(active),
            "promoted": len(promoted),
            "held": len(held),
            "dormant": len(dormant),
            "genome_id": genome,
            "mood_dot": round(mood_dot, 4),
            "cycle_count": self.cycle_count,
            "members": [
                {
                    "id": c["id"],
                    "genome_id": c.get("genome_id"),
                    "fusion_state_id": c.get("fusion_state_id", ""),
                    "state": c.get("state"),
                    "promoted": c.get("promoted", False),
                    "ns_fitness": c.get("ns_fitness", 0.0),
                    "mood_dot": c.get("mood_dot", 0.5),
                    "mood": c.get("mood", "neutral"),
                    "fitness_evidence": c.get("fitness_evidence", {}),
                }
                for c in civs
            ],
            "fusion_history": self.fusion_log[-100:],
            "promotion_history": self.promote_log[-100:],
        }

    def simulate_cycle(self):
        """Advance geometry, fusion, and lineage under one snapshot lock."""
        with self._descent_state_lock:
            self._simulate_cycle_locked()

    def _simulate_cycle_locked(self):
        self.cycle_count += 1
        descent_record = self.descent_engine.tick()
        residual = descent_record["residual"]
        great_scale_descent_ticks.inc()
        great_scale_descent_residual.labels(universe_id=self.id).set(residual)
        great_scale_descent_x.labels(universe_id=self.id).set(descent_record["x"])

        for civ in self.civilizations.values():
            if civ["state"] not in ("active", "promoted"):
                continue
            civ["resources"]["attention"] = max(0, civ["resources"]["attention"] - 1)
            if civ["resources"]["compute"] >= 10:
                civ["resources"]["compute"] -= 10
                civ["resources"]["memory_nodes"] += 1
            drift = np.random.uniform(-0.01, 0.01)
            civ["belief"]["truth"] = float(np.clip(civ["belief"]["truth"] + drift, 0, 1))
            civ["belief"]["deception"] = 1 - civ["belief"]["truth"]
            mood = "neutral"
            if civ["resources"]["attention"] < 12:
                mood = "survival"
            elif civ["belief"]["truth"] > 0.62:
                mood = "convergent"
            base_entropy = 0.15 + (0.5 if mood == "survival" else 0.0)
            entropy = entropy_with_stress(base_entropy, residual)
            channels = fitness_channels(
                belief=civ["belief"],
                resources=civ["resources"],
                core=civ["belief"]["truth"],
                entropy=entropy,
                coupling=0.08 if mood == "convergent" else 0.02,
            )
            fit = channels["ns_fitness"]
            fused = fuse_mood(fit, mood)
            decision = promote_decision(fused, already_promoted=bool(civ.get("promoted")))
            label = mood
            label_projection_threshold = None
            if fused >= 0.70 and mood == "neutral":
                label = "convergent"
                label_projection_threshold = "convergent_label"
            elif fused < 0.30 and mood != "survival":
                label = "survival"
                label_projection_threshold = "survival_label"
            evidence = build_fitness_evidence(
                channels,
                fused,
                stress_residual=residual,
                stress_residual_normalized=residual / 7.0,
                neural_entropy_used=entropy,
                descent_source="simulation_scheduler",
                mood_input=mood,
                mood_output=label,
                label_projection_threshold=label_projection_threshold,
                metric_source="simulation_scheduler",
            )
            identity_state = build_fusion_identity_state(
                mood_input=mood,
                mood_output=label,
                channels=channels,
                fused=fused,
                core=float(civ["belief"]["truth"]),
                base_entropy=base_entropy,
                neural_entropy_used=entropy,
                coupling=0.08 if mood == "convergent" else 0.02,
                belief=civ["belief"],
                resources=civ["resources"],
                stress_residual=residual,
                descent_source="simulation_scheduler",
                metric_source="simulation_scheduler",
            )
            state_id = fitness_state_id(identity_state)
            evidence["fusion_state_id"] = state_id
            civ["ns_fitness"] = round(fit, 4)
            civ["mood_dot"] = round(fused, 4)
            civ["mood"] = label
            civ["fusion_state_id"] = state_id
            civ["fitness_evidence"] = evidence
            civ["stress_residual"] = residual
            civ["stress_residual_normalized"] = round(residual / 7.0, 8)
            civ["neural_entropy_used"] = round(entropy, 8)
            fusion_event = {
                "cycle": self.cycle_count,
                "civ_id": civ["id"],
                "genome_id": civ.get("genome_id", ""),
                "fusion_state_id": state_id,
                "ns_fitness": round(fit, 4),
                "mood_dot": round(fused, 4),
                "action": decision["action"],
                "metric_source": "simulation_scheduler",
                "fitness_evidence": evidence,
            }
            self.fusion_log.append(fusion_event)
            if len(self.fusion_log) > self.max_fusion_log:
                del self.fusion_log[:-self.max_fusion_log]
            if decision["action"] == "promote":
                civ["promoted"] = True
                civ["state"] = "promoted"
                self.promote_log.append({"civ_id": civ["id"], "action": "promote", "fused": decision["fused"], "cycle": self.cycle_count, "genome_id": civ.get("genome_id", ""), "fusion_state_id": state_id, "fitness_evidence": evidence})
                if len(self.promote_log) > self.max_promotion_log:
                    del self.promote_log[:-self.max_promotion_log]
            elif decision["action"] == "demote":
                civ["promoted"] = False
                civ["state"] = "active"
                self.promote_log.append({"civ_id": civ["id"], "action": "demote", "fused": decision["fused"], "cycle": self.cycle_count, "genome_id": civ.get("genome_id", ""), "fusion_state_id": state_id, "fitness_evidence": evidence})
                if len(self.promote_log) > self.max_promotion_log:
                    del self.promote_log[:-self.max_promotion_log]
        logger.debug(f"Completed cycle {self.cycle_count} for universe {self.id}")

    def descent_snapshot(self, running=False):
        with self._descent_state_lock:
            return self.descent_engine.snapshot(running=running)

    def scale_state_snapshot(self, running=False):
        with self._descent_state_lock:
            snapshot = self.descent_engine.snapshot(running=running)
            return {
                **snapshot,
                "universe_id": self.id,
                "cycle_count": self.cycle_count,
                "stress_residual_normalized": snapshot["residualNormalized"],
            }

class CycleKernel:
    def __init__(self):
        self.universes = {}
        self.audit_logs = []
        self.running = False

    def create_universe(self, universe_id):
        if universe_id not in self.universes:
            self.universes[universe_id] = Universe(universe_id)
            logger.info(f"Created universe {universe_id}")
        return self.universes[universe_id]

    def run_simulation(self, cycles=1):
        start_time = time.time()
        for _ in range(cycles):
            for universe in self.universes.values():
                universe.simulate_cycle()
            simulation_cycles.inc()
        duration = time.time() - start_time
        simulation_duration.observe(duration)
        total_civs = sum(len(u.civilizations) for u in self.universes.values())
        total_att = sum(sum(c["resources"]["attention"] for c in u.civilizations.values()) for u in self.universes.values())
        total_comp = sum(sum(c["resources"]["compute"] for c in u.civilizations.values()) for u in self.universes.values())
        promoted = sum(1 for u in self.universes.values() for c in u.civilizations.values() if c.get("promoted"))
        active_civilizations.set(total_civs)
        total_attention.set(total_att)
        total_compute.set(total_comp)
        promoted_colonists.set(promoted)
        logger.info(f"Ran {cycles} simulation cycles in {duration:.3f}s")

    def colony(self):
        snapshots = {uid: u.colony_snapshot() for uid, u in self.universes.items()}
        primary = snapshots.get("U1") or next(iter(snapshots.values()), {})
        return {"universes": snapshots, **{k: primary.get(k) for k in ("active", "promoted", "held", "dormant", "genome_id", "mood_dot")}}

    def get_state(self):
        return {
            "universes": {
                uid: {
                    "id": u.id,
                    "civilizations": u.civilizations,
                    "factions": u.factions,
                    "cycle_count": u.cycle_count,
                    "colony": u.colony_snapshot(),
                    "descent": u.descent_snapshot(running=self.running),
                }
                for uid, u in self.universes.items()
            },
            "total_civilizations": sum(len(u.civilizations) for u in self.universes.values()),
            "colony": self.colony(),
            "audit_logs": self.audit_logs[-100:],
        }


class ChatMemoryBridge:
    def __init__(self, kernel, universes):
        self.kernel = kernel
        self.universes = universes
        self.chat_to_civ_map = {}

    def process_interaction(self, user_id, message, response):
        u1 = self.universes.get("U1")
        if not u1:
            u1 = self.kernel.create_universe("U1")
        civ_id = self.chat_to_civ_map.get(user_id)
        if not civ_id or civ_id not in u1.civilizations:
            civ_id = f"user_{user_id[:6]}"
            u1.add_civilization(civ_id)
            self.chat_to_civ_map[user_id] = civ_id
        civ = u1.civilizations[civ_id]
        civ["resources"]["attention"] = min(150, civ["resources"]["attention"] + 10)
        civ["resources"]["compute"] += 5
        message_impact = len(message) / 1000
        civ["belief"]["truth"] = float(np.clip(civ["belief"]["truth"] + message_impact, 0, 1))
        civ["belief"]["deception"] = 1 - civ["belief"]["truth"]
        event = {
            "type": "chat_interaction",
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "impact": {"civ_id": civ_id, "attention_delta": 10, "compute_delta": 5, "genome_id": civ.get("genome_id")},
        }
        self.kernel.audit_logs.append(event)
        chat_interactions.inc()
        socketio.emit("event", {"message": f"Memory updated for {civ_id} genome {civ.get('genome_id')}", "civ_state": civ})
        logger.info(f"Processed interaction for user {user_id} -> civ {civ_id}")
        return civ_id

    def get_context_from_memory(self, user_id):
        civ_id = self.chat_to_civ_map.get(user_id)
        if not civ_id:
            return {"status": "new_user", "message": "New user, no prior memory."}
        u1 = self.universes.get("U1")
        if not u1:
            return {"status": "no_universe", "message": "Universe not initialized."}
        civ = u1.civilizations.get(civ_id)
        if not civ:
            return {"status": "no_civ", "message": "Civilization not found."}
        related_myths = [m for m in u1.myths.values() if m.get("faction") == civ["faction"]]
        return {
            "status": "success",
            "user_state": civ,
            "crystallized_memories": related_myths,
            "universe_vibe": {
                "total_civs": len(u1.civilizations),
                "active_factions": u1.factions,
                "cycle_count": u1.cycle_count,
                "colony": u1.colony_snapshot(),
            },
        }


kernel = CycleKernel()
u1 = kernel.create_universe("U1")
bridge = ChatMemoryBridge(kernel, kernel.universes)
for i in range(3):
    u1.add_civilization(f"civ_{i}")


@app.route("/health", methods=["GET"])
def health():
    colony = kernel.colony()
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat(), "genome_id": colony.get("genome_id"), "promoted": colony.get("promoted", 0)})


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest()


@app.route("/state", methods=["GET"])
def get_state():
    return jsonify(kernel.get_state())


@app.route("/api/v1/scale/state", methods=["GET"])
def get_scale_state():
    """Read-only Great Scale snapshot; fail closed unless a bearer token is configured."""
    expected_token = os.environ.get("SCALE_API_TOKEN", "")
    if not expected_token:
        return jsonify({"status": "unavailable", "error": "SCALE_API_TOKEN is not configured"}), 503
    provided = request.headers.get("Authorization", "")
    if not hmac.compare_digest(provided, f"Bearer {expected_token}"):
        return jsonify({"status": "unauthorized"}), 401
    universe = kernel.universes.get("U1") or next(iter(kernel.universes.values()), None)
    if universe is None:
        return jsonify({"status": "unavailable", "error": "no universe exists"}), 503
    return jsonify(universe.scale_state_snapshot(running=kernel.running))


@app.route("/colony", methods=["GET"])
def colony():
    return jsonify(kernel.colony())


@app.route("/simulate/<int:cycles>", methods=["POST"])
def simulate(cycles):
    if cycles < 1 or cycles > 1000:
        return jsonify({"status": "error", "message": "cycles must be between 1 and 1000"}), 400
    kernel.run_simulation(cycles)
    return jsonify({"status": "success", "cycles": cycles, "colony": kernel.colony(), "descent": {uid: u.descent_snapshot(running=kernel.running) for uid, u in kernel.universes.items()}})


@app.route("/chat/interact", methods=["POST"])
def chat_interact():
    data = request.json or {}
    user_id = data.get("user_id", "anonymous")
    message = data.get("message", "")
    response = data.get("response", "")
    civ_id = bridge.process_interaction(user_id, message, response)
    context = bridge.get_context_from_memory(user_id)
    return jsonify({"status": "success", "civ_id": civ_id, "context": context})


@app.route("/chat/context/<user_id>", methods=["GET"])
def get_context(user_id):
    return jsonify(bridge.get_context_from_memory(user_id))


def background_simulation():
    while kernel.running:
        kernel.run_simulation(1)
        socketio.sleep(5)


@socketio.on("connect")
def handle_connect():
    logger.info("Client connected")
    socketio.emit("status", {"message": "Connected to CycleKernel"})


@socketio.on("start_simulation")
def handle_start_simulation():
    if not kernel.running:
        kernel.running = True
        socketio.start_background_task(background_simulation)
        logger.info("Started background simulation")
    socketio.emit("status", {"message": "Simulation started"})


@socketio.on("stop_simulation")
def handle_stop_simulation():
    kernel.running = False
    logger.info("Stopped background simulation")
    socketio.emit("status", {"message": "Simulation stopped"})


if __name__ == "__main__":
    logger.info("Starting CycleKernel Simulation Server")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
