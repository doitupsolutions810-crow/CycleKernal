"""
Neuro-Symbolic AI Layer for CycleKernel
=======================================
Hybrid architecture:

  Neural  (sub-symbolic): continuous scores from LoopMem metrics + genome weights
  Symbolic (rules):        discrete if-then trait rules, tool selection logic, safety

The reasoner fuses both:
  1. NeuralScore vectors estimate soft activations for each trait / tool
  2. SymbolicRule set hard-gates safety and forces required structure
  3. Final decision = symbolic filter over neural ranking
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Neural side — continuous scoring (no external ML deps; pure math "tiny net")
# ---------------------------------------------------------------------------

@dataclass
class NeuralScore:
    name: str
    score: float  # 0..1
    features: Dict[str, float] = field(default_factory=dict)


def _sigmoid(x: float) -> float:
    # stable sigmoid
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def neural_trait_activations(metrics: Dict[str, float], weights: Optional[Dict[str, float]] = None) -> List[NeuralScore]:
    """
    Tiny hand-crafted 'network': weighted features → sigmoid activations.
    weights can come from evolved genome (divergent_weight, etc.).
    """
    weights = weights or {}
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    l2 = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    l5 = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    u2 = float(metrics.get("U2", 0.5))

    w_div = weights.get("divergent_weight", 1.0)
    w_con = weights.get("convergent_weight", 1.0)
    w_sur = weights.get("survival_weight", 1.0)

    # Feature engineering
    scores = [
        NeuralScore(
            "Creative/Divergent",
            _sigmoid(w_div * (3.0 * (l5 - 0.6) + 0.5 * (1.0 - core))),
            {"l5": l5, "core": core},
        ),
        NeuralScore(
            "Analytical/Convergent",
            _sigmoid(w_con * (40.0 * (l2 - 0.03) + 0.3 * u2)),
            {"l2": l2, "u2": u2},
        ),
        NeuralScore(
            "Survival/Conservation",
            _sigmoid(w_sur * (5.0 * (0.2 - core) + 0.2 * l2)),
            {"core": core, "l2": l2},
        ),
        NeuralScore(
            "High-Confidence",
            _sigmoid(6.0 * (u2 - 0.55)),
            {"u2": u2},
        ),
        NeuralScore(
            "Exploratory-Uncertainty",
            _sigmoid(6.0 * (0.35 - u2)),
            {"u2": u2},
        ),
    ]
    return scores


def neural_tool_ranking(goal: str, metrics: Dict[str, float]) -> List[NeuralScore]:
    """Soft ranking of which tool fits a goal + current mood metrics."""
    g = goal.lower()
    l5 = float(metrics.get("L5", metrics.get("entropy", 0.5)))
    core = float(metrics.get("Core", metrics.get("core", 0.5)))

    def has(*keys: str) -> float:
        return 1.0 if any(k in g for k in keys) else 0.0

    candidates = {
        "research": 0.3 + 0.5 * has("research", "look up", "what is", "search") + 0.2 * l5,
        "scrape": 0.2 + 0.7 * has("http://", "https://", "scrape", "website", "url"),
        "planning": 0.25 + 0.55 * has("plan", "steps", "break down", "how should"),
        "coding": 0.25 + 0.6 * has("code", "function", "script", "implement", "python"),
        "pipeline": 0.2 + 0.65 * has("build", "create", "full", "pipeline", "solve") + 0.1 * (1 - core),
        "get_mood": 0.15 + 0.7 * has("mood", "feeling", "cognitive"),
        "terminal_execute": 0.1 + 0.5 * has("run", "execute", "shell"),
    }
    ranked = [
        NeuralScore(name, _sigmoid(2.0 * (score - 0.4)), {"raw": score})
        for name, score in candidates.items()
    ]
    ranked.sort(key=lambda s: -s.score)
    return ranked


# ---------------------------------------------------------------------------
# Symbolic side — explicit rules
# ---------------------------------------------------------------------------

@dataclass
class SymbolicRule:
    name: str
    description: str
    # predicate(metrics, goal) -> bool
    when: Callable[[Dict[str, float], str], bool]
    # effect: forced traits or forced tool
    force_traits: List[str] = field(default_factory=list)
    force_tool: Optional[str] = None
    forbid_tools: List[str] = field(default_factory=list)
    priority: int = 0  # higher wins


def default_symbolic_rules() -> List[SymbolicRule]:
    return [
        SymbolicRule(
            name="survival_lock",
            description="Low core forces survival trait and forbids pipeline risk",
            when=lambda m, g: float(m.get("Core", m.get("core", 1.0))) < 0.1,
            force_traits=["Survival/Conservation"],
            forbid_tools=["pipeline"],
            priority=100,
        ),
        SymbolicRule(
            name="url_requires_scrape",
            description="If goal contains URL, require scrape or research",
            when=lambda m, g: "http://" in g.lower() or "https://" in g.lower(),
            force_tool="scrape",
            priority=80,
        ),
        SymbolicRule(
            name="explicit_code",
            description="Code keywords force coding tool",
            when=lambda m, g: any(k in g.lower() for k in ("write code", "python function", "implement function")),
            force_tool="coding",
            priority=70,
        ),
        SymbolicRule(
            name="build_implies_pipeline",
            description="Build/create goals prefer full pipeline",
            when=lambda m, g: any(k in g.lower() for k in ("build ", "create a", "full pipeline")),
            force_tool="pipeline",
            priority=60,
        ),
        SymbolicRule(
            name="high_entropy_allows_speculative",
            description="Mark speculative trait under high entropy",
            when=lambda m, g: float(m.get("L5", m.get("entropy", 0))) > 0.8,
            force_traits=["Creative/Divergent"],
            priority=40,
        ),
    ]


# ---------------------------------------------------------------------------
# Fusion reasoner
# ---------------------------------------------------------------------------

@dataclass
class NeuroSymbolicDecision:
    traits: List[str]
    tool: Optional[str]
    neural_trait_scores: List[Dict[str, Any]]
    neural_tool_scores: List[Dict[str, Any]]
    applied_rules: List[str]
    explanation: str
    system_prompt_override: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "traits": self.traits,
            "tool": self.tool,
            "neural_trait_scores": self.neural_trait_scores,
            "neural_tool_scores": self.neural_tool_scores,
            "applied_rules": self.applied_rules,
            "explanation": self.explanation,
            "system_prompt_override": self.system_prompt_override,
        }


class NeuroSymbolicReasoner:
    """
    Fuses neural activations with symbolic rules.

    Algorithm:
      1. Compute neural trait activations & tool ranking
      2. Collect symbolic rule firings (sorted by priority)
      3. Traits = neural above threshold ∪ forced traits
      4. Tool = forced tool if any, else top neural tool not forbidden
      5. Build prompt overrides from final traits
    """

    def __init__(
        self,
        rules: Optional[List[SymbolicRule]] = None,
        trait_threshold: float = 0.55,
        genome_weights: Optional[Dict[str, float]] = None,
    ):
        self.rules = rules or default_symbolic_rules()
        self.trait_threshold = trait_threshold
        self.genome_weights = genome_weights or {}

    def reason(self, metrics: Dict[str, float], goal: str = "") -> NeuroSymbolicDecision:
        # Neural
        trait_scores = neural_trait_activations(metrics, self.genome_weights)
        tool_scores = neural_tool_ranking(goal, metrics)

        # Symbolic
        fired = [r for r in self.rules if r.when(metrics, goal)]
        fired.sort(key=lambda r: -r.priority)

        forced_traits: List[str] = []
        forbid: List[str] = []
        forced_tool: Optional[str] = None
        for r in fired:
            forced_traits.extend(r.force_traits)
            forbid.extend(r.forbid_tools)
            if r.force_tool and forced_tool is None:
                forced_tool = r.force_tool

        # Fuse traits
        traits = [s.name for s in trait_scores if s.score >= self.trait_threshold]
        for t in forced_traits:
            if t not in traits:
                traits.append(t)
        if not traits:
            traits = ["Neutral-Baseline"]

        # Fuse tool — forced tools still respect forbid list (safety wins)
        tool = forced_tool if forced_tool and forced_tool not in forbid else None
        if tool is None:
            for s in tool_scores:
                if s.name not in forbid:
                    tool = s.name
                    break

        # Prompt synthesis (symbolic templates)
        prompts = []
        if "Creative/Divergent" in traits:
            prompts.append(
                "SYSTEM OVERRIDE [NEURO-SYMBOLIC/DIVERGENT]: Prefer exploratory hypotheses; "
                "delay convergence."
            )
        if "Analytical/Convergent" in traits:
            prompts.append(
                "SYSTEM OVERRIDE [NEURO-SYMBOLIC/CONVERGENT]: Chain evidence tightly; "
                "prefer precise answers."
            )
        if "Survival/Conservation" in traits:
            prompts.append(
                "SYSTEM OVERRIDE [NEURO-SYMBOLIC/SURVIVAL]: Minimize irreversible actions; "
                "prefer known-safe tools."
            )

        explanation = (
            f"Neural top trait={trait_scores[0].name}({trait_scores[0].score:.2f}); "
            f"tool={tool}; rules={[r.name for r in fired]}"
        )

        return NeuroSymbolicDecision(
            traits=traits,
            tool=tool,
            neural_trait_scores=[{"name": s.name, "score": round(s.score, 4)} for s in trait_scores],
            neural_tool_scores=[{"name": s.name, "score": round(s.score, 4)} for s in tool_scores[:5]],
            applied_rules=[r.name for r in fired],
            explanation=explanation,
            system_prompt_override="\n\n".join(prompts),
        )
