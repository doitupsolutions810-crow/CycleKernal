"""
CycleKernel Simulation Core with ChatMemoryBridge Integration
Combines the simulation engine with memory-based chat interactions
"""

import numpy as np
from datetime import datetime
import json
import time
from flask import Flask, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
from prometheus_client import Counter, Gauge, Histogram, generate_latest
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics
simulation_cycles = Counter('simulation_cycles_total', 'Total simulation cycles executed')
active_civilizations = Gauge('active_civilizations', 'Number of active civilizations')
total_attention = Gauge('total_attention', 'Total attention across all civilizations')
total_compute = Gauge('total_compute', 'Total compute resources')
chat_interactions = Counter('chat_interactions_total', 'Total chat interactions processed')
simulation_duration = Histogram('simulation_cycle_duration_seconds', 'Time taken for simulation cycles')

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------------- CIVILIZATION TEMPLATE ----------------
def civ_template(civ_id):
    """Create a new civilization with default values"""
    return {
        "id": civ_id,
        "faction": np.random.choice(["Truth", "Deception", "Neutral"]),
        "resources": {
            "attention": 50,
            "compute": 20,
            "memory_nodes": 1
        },
        "belief": {
            "truth": 0.5,
            "deception": 0.5
        },
        "state": "active",
        "created_at": datetime.now().isoformat()
    }

# ---------------- UNIVERSE CLASS ----------------
class Universe:
    def __init__(self, universe_id):
        self.id = universe_id
        self.civilizations = {}
        self.factions = {"Truth": 0, "Deception": 0, "Neutral": 0}
        self.myths = {}
        self.cycle_count = 0
        
    def add_civilization(self, civ_id):
        """Add a new civilization to the universe"""
        if civ_id not in self.civilizations:
            civ = civ_template(civ_id)
            self.civilizations[civ_id] = civ
            self.factions[civ["faction"]] += 1
            logger.info(f"Added civilization {civ_id} to universe {self.id}")
            return civ
        return self.civilizations[civ_id]
    
    def simulate_cycle(self):
        """Run one simulation cycle for all civilizations"""
        self.cycle_count += 1
        
        for civ_id, civ in self.civilizations.items():
            if civ["state"] == "active":
                # Decay attention over time
                civ["resources"]["attention"] = max(0, civ["resources"]["attention"] - 1)
                
                # Compute generates memory nodes
                if civ["resources"]["compute"] >= 10:
                    civ["resources"]["compute"] -= 10
                    civ["resources"]["memory_nodes"] += 1
                
                # Belief drift
                drift = np.random.uniform(-0.01, 0.01)
                civ["belief"]["truth"] = np.clip(civ["belief"]["truth"] + drift, 0, 1)
                civ["belief"]["deception"] = 1 - civ["belief"]["truth"]
        
        logger.debug(f"Completed cycle {self.cycle_count} for universe {self.id}")

# ---------------- CYCLEKERNEL CLASS ----------------
class CycleKernel:
    def __init__(self):
        self.universes = {}
        self.audit_logs = []
        self.running = False
        
    def create_universe(self, universe_id):
        """Create a new universe"""
        if universe_id not in self.universes:
            self.universes[universe_id] = Universe(universe_id)
            logger.info(f"Created universe {universe_id}")
        return self.universes[universe_id]
    
    def run_simulation(self, cycles=1):
        """Run simulation for specified number of cycles"""
        start_time = time.time()
        
        for _ in range(cycles):
            for universe in self.universes.values():
                universe.simulate_cycle()
            simulation_cycles.inc()
        
        duration = time.time() - start_time
        simulation_duration.observe(duration)
        
        # Update Prometheus metrics
        total_civs = sum(len(u.civilizations) for u in self.universes.values())
        total_att = sum(
            sum(c["resources"]["attention"] for c in u.civilizations.values())
            for u in self.universes.values()
        )
        total_comp = sum(
            sum(c["resources"]["compute"] for c in u.civilizations.values())
            for u in self.universes.values()
        )
        
        active_civilizations.set(total_civs)
        total_attention.set(total_att)
        total_compute.set(total_comp)
        
        logger.info(f"Ran {cycles} simulation cycles in {duration:.3f}s")
    
    def get_state(self):
        """Get current state of all universes"""
        return {
            "universes": {
                uid: {
                    "id": u.id,
                    "civilizations": u.civilizations,
                    "factions": u.factions,
                    "cycle_count": u.cycle_count
                }
                for uid, u in self.universes.items()
            },
            "total_civilizations": sum(len(u.civilizations) for u in self.universes.values()),
            "audit_logs": self.audit_logs[-100:]  # Last 100 logs
        }

# ---------------- CHATBOT MEMORY BRIDGE ----------------
class ChatMemoryBridge:
    """Bridge between chat interactions and CycleKernel simulation"""
    
    def __init__(self, kernel, universes):
        self.kernel = kernel
        self.universes = universes
        self.chat_to_civ_map = {}
        
    def process_interaction(self, user_id, message, response):
        """Process a chat interaction and update the simulation"""
        u1 = self.universes.get("U1")
        if not u1:
            u1 = self.kernel.create_universe("U1")
        
        # Map user to civilization
        civ_id = self.chat_to_civ_map.get(user_id)
        if not civ_id or civ_id not in u1.civilizations:
            civ_id = f"user_{user_id[:6]}"
            u1.add_civilization(civ_id)
            self.chat_to_civ_map[user_id] = civ_id
            
        civ = u1.civilizations[civ_id]
        
        # Update resources based on interaction
        civ["resources"]["attention"] = min(150, civ["resources"]["attention"] + 10)
        civ["resources"]["compute"] += 5
        
        # Influence belief based on message length and sentiment
        message_impact = len(message) / 1000
        civ["belief"]["truth"] = np.clip(civ["belief"]["truth"] + message_impact, 0, 1)
        civ["belief"]["deception"] = 1 - civ["belief"]["truth"]
        
        # Log the event
        event = {
            "type": "chat_interaction",
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "impact": {
                "civ_id": civ_id,
                "attention_delta": 10,
                "compute_delta": 5
            }
        }
        self.kernel.audit_logs.append(event)
        
        # Update metrics
        chat_interactions.inc()
        
        # Emit socket event
        socketio.emit("event", {
            "message": f"Memory updated for {civ_id}: Attention +10, Compute +5",
            "civ_state": civ
        })
        
        logger.info(f"Processed interaction for user {user_id} -> civ {civ_id}")
        return civ_id

    def get_context_from_memory(self, user_id):
        """Retrieve context from memory for a user"""
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
                "cycle_count": u1.cycle_count
            }
        }

# ---------------- INITIALIZE KERNEL ----------------
kernel = CycleKernel()
u1 = kernel.create_universe("U1")
bridge = ChatMemoryBridge(kernel, kernel.universes)

# Add some initial civilizations
for i in range(3):
    u1.add_civilization(f"civ_{i}")

# ---------------- API ENDPOINTS ----------------
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest()

@app.route('/state', methods=['GET'])
def get_state():
    """Get current simulation state"""
    return jsonify(kernel.get_state())

@app.route('/simulate/<int:cycles>', methods=['POST'])
def simulate(cycles):
    """Run simulation for N cycles"""
    kernel.run_simulation(cycles)
    return jsonify({"status": "success", "cycles": cycles})

@app.route('/chat/interact', methods=['POST'])
def chat_interact():
    """Process a chat interaction"""
    from flask import request
    data = request.json
    user_id = data.get('user_id', 'anonymous')
    message = data.get('message', '')
    response = data.get('response', '')
    
    civ_id = bridge.process_interaction(user_id, message, response)
    context = bridge.get_context_from_memory(user_id)
    
    return jsonify({
        "status": "success",
        "civ_id": civ_id,
        "context": context
    })

@app.route('/chat/context/<user_id>', methods=['GET'])
def get_context(user_id):
    """Get memory context for a user"""
    context = bridge.get_context_from_memory(user_id)
    return jsonify(context)

# ---------------- BACKGROUND SIMULATION ----------------
def background_simulation():
    """Run simulation in background"""
    while kernel.running:
        kernel.run_simulation(1)
        socketio.sleep(5)  # Run every 5 seconds

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info("Client connected")
    socketio.emit('status', {'message': 'Connected to CycleKernel'})

@socketio.on('start_simulation')
def handle_start_simulation():
    """Start background simulation"""
    if not kernel.running:
        kernel.running = True
        socketio.start_background_task(background_simulation)
        logger.info("Started background simulation")
    socketio.emit('status', {'message': 'Simulation started'})

@socketio.on('stop_simulation')
def handle_stop_simulation():
    """Stop background simulation"""
    kernel.running = False
    logger.info("Stopped background simulation")
    socketio.emit('status', {'message': 'Simulation stopped'})

if __name__ == '__main__':
    logger.info("Starting CycleKernel Simulation Server")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
