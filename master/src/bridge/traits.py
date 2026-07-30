"""
Evo-Psych Trait Mapper — CycleKernel Ghost Sync v4.0
Maps LoopMem metrics into cognitive overrides used by every sub-agent.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict
from datetime import datetime

@dataclass
class CognitiveState:
    mood: str = "neutral"
    traits: List[str] = field(default_factory=list)
    system_prompt_override: str = ""
    metrics: Dict = field(default_factory=dict)
    entropy: float = 0.0
    coupling: float = 0.0
    core: float = 0.5
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    explanation: str = "Baseline consciousness vector."

    def to_dict(self):
        return asdict(self)


def map_metrics_to_traits(metrics: Dict) -> CognitiveState:
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    l2 = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    l5 = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    u2 = float(metrics.get("U2", 0.0))

    state = CognitiveState(metrics=metrics, entropy=l5, coupling=l2, core=core)
    traits, prompts = [], []

    if l5 > 0.8:
        traits.append("Creative/Divergent")
        prompts.append(
            "SYSTEM OVERRIDE [HIGH ENTROPY]: Prioritize divergent ideation, novel analogies, "
            "exploratory branching. Suppress premature convergence."
        )
        state.mood = "divergent"
        state.explanation = "Current State: High Entropy — Expect Divergent Answers"

    if l2 > 0.05:
        traits.append("Analytical/Convergent")
        prompts.append(
            "SYSTEM OVERRIDE [HIGH COUPLING]: Enforce rigorous logical chaining, precision, "
            "evidence-bound reasoning."
        )
        state.mood = "balanced-tension" if state.mood == "divergent" else "convergent"
        state.explanation = "Current State: High Coupling — Expect Analytical Precision"

    if core < 0.1:
        traits.append("Survival/Conservation")
        prompts.append(
            "SYSTEM OVERRIDE [LOW CORE]: Activate conservation protocols. Minimize risk, "
            "prefer stable known solutions."
        )
        state.mood = "survival"
        state.explanation = "Current State: Low Core — Survival Protocols Active"

    if u2 > 0.7:
        traits.append("High-Confidence")
    elif u2 < 0.2:
        traits.append("Exploratory-Uncertainty")

    if not traits:
        traits.append("Neutral-Baseline")
        state.mood = "neutral"
        state.explanation = "LoopMem within nominal bounds."

    state.traits = traits
    state.system_prompt_override = "\n\n".join(prompts)
    return state
