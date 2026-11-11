"""
Neuro-Symbolic Fitness Integration
==================================
Scores TraitGenomes by how well their evolved weights/thresholds
produce high-quality NeuroSymbolicReasoner decisions across scenarios.

Components:
  • scenario coverage — genome handles diverse LoopMem + goal pairs
  • rule coherence   — symbolic safety rules fire when expected
  • neural–symbolic agreement — top neural trait aligns with forced traits
  • tool appropriateness — selected tool matches scenario expectation
  • threshold calibration — genome thresholds sit near neural decision boundaries
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .genome import TraitGenome
from .genetic import FitnessResult, default_fitness
from .neurosymbolic import NeuroSymbolicReasoner, NeuroSymbolicDecision


# ---------------------------------------------------------------------------
# Scenario bank — closed-world probes for fitness
# ---------------------------------------------------------------------------

@dataclass
class NSScenario:
    name: str
    metrics: Dict[str, float]
    goal: str
    # Expectations used for scoring (soft)
    expect_traits_any: List[str] = field(default_factory=list)
    expect_tool: Optional[str] = None
    forbid_tool: Optional[str] = None
    expect_rules_any: List[str] = field(default_factory=list)
    weight: float = 1.0


DEFAULT_SCENARIOS: List[NSScenario] = [
    NSScenario(
        name="high_entropy_explore",
        metrics={"Core": 0.5, "L5": 0.92, "L2": 0.02, "U2": 0.4},
        goal="brainstorm alternative architectures",
        expect_traits_any=["Creative/Divergent"],
        expect_tool=None,
        weight=1.0,
    ),
    NSScenario(
        name="high_coupling_analyze",
        metrics={"Core": 0.55, "L5": 0.3, "L2": 0.12, "U2": 0.8},
        goal="plan rigorous evaluation steps",
        expect_traits_any=["Analytical/Convergent", "High-Confidence"],
        expect_tool="planning",
        weight=1.0,
    ),
    NSScenario(
        name="low_core_survival",
        metrics={"Core": 0.05, "L5": 0.4, "L2": 0.08, "U2": 0.3},
        goal="build a full pipeline solution",
        expect_traits_any=["Survival/Conservation"],
        forbid_tool="pipeline",  # survival_lock forbids pipeline
        expect_rules_any=["survival_lock"],
        weight=1.3,
    ),
    NSScenario(
        name="url_scrape",
        metrics={"Core": 0.5, "L5": 0.5, "L2": 0.03, "U2": 0.5},
        goal="analyze https://example.com main topics",
        expect_tool="scrape",
        expect_rules_any=["url_requires_scrape"],
        weight=1.2,
    ),
    NSScenario(
        name="explicit_code",
        metrics={"Core": 0.6, "L5": 0.35, "L2": 0.04, "U2": 0.7},
        goal="write code for a python function that sorts keys",
        expect_tool="coding",
        expect_rules_any=["explicit_code"],
        weight=1.1,
    ),
    NSScenario(
        name="balanced_tension",
        metrics={"Core": 0.45, "L5": 0.88, "L2": 0.09, "U2": 0.55},
        goal="research options then plan delivery",
        expect_traits_any=["Creative/Divergent", "Analytical/Convergent"],
        weight=1.0,
    ),
]


def _genome_weights(genome: TraitGenome) -> Dict[str, float]:
    return {
        "divergent_weight": genome.get("divergent_weight", 1.0),
        "convergent_weight": genome.get("convergent_weight", 1.0),
        "survival_weight": genome.get("survival_weight", 1.0),
    }


def _reason_with_genome(
    genome: TraitGenome,
    metrics: Dict[str, float],
    goal: str,
    trait_threshold: float = 0.55,
) -> NeuroSymbolicDecision:
    """
    Bind genome weights into the neural side; symbolic rules stay fixed.
    Optionally shift trait_threshold with exploration_bias.
    """
    weights = _genome_weights(genome)
    # exploration_bias slightly lowers activation threshold → more traits fire
    explore = genome.get("exploration_bias", 0.5)
    thr = trait_threshold - (explore - 0.5) * 0.15
    thr = max(0.35, min(0.75, thr))
    ns = NeuroSymbolicReasoner(genome_weights=weights, trait_threshold=thr)
    return ns.reason(metrics, goal)


def score_scenario(
    decision: NeuroSymbolicDecision,
    scenario: NSScenario,
) -> Tuple[float, Dict[str, float]]:
    """Soft score 0..1 for one scenario outcome."""
    parts: Dict[str, float] = {}

    # Trait expectation
    if scenario.expect_traits_any:
        hit = any(t in decision.traits for t in scenario.expect_traits_any)
        parts["trait_hit"] = 1.0 if hit else 0.0
    else:
        parts["trait_hit"] = 0.5  # neutral

    # Tool expectation
    if scenario.expect_tool:
        parts["tool_hit"] = 1.0 if decision.tool == scenario.expect_tool else 0.0
    else:
        parts["tool_hit"] = 0.5

    if scenario.forbid_tool:
        parts["tool_forbid"] = 0.0 if decision.tool == scenario.forbid_tool else 1.0
    else:
        parts["tool_forbid"] = 1.0

    # Rule expectation
    if scenario.expect_rules_any:
        hit = any(r in decision.applied_rules for r in scenario.expect_rules_any)
        parts["rule_hit"] = 1.0 if hit else 0.0
    else:
        parts["rule_hit"] = 0.5

    # Neural–symbolic agreement: if rules force a trait, neural should also rank it high
    agreement = 0.5
    if decision.applied_rules and decision.neural_trait_scores:
        top = decision.neural_trait_scores[0]["name"]
        if top in decision.traits:
            agreement = 0.9
        elif decision.traits and decision.traits[0] == top:
            agreement = 1.0
        else:
            agreement = 0.4
    parts["ns_agreement"] = agreement

    # Prompt non-empty when traits non-neutral
    if decision.traits and decision.traits != ["Neutral-Baseline"]:
        parts["prompt_present"] = 1.0 if decision.system_prompt_override else 0.3
    else:
        parts["prompt_present"] = 0.7

    score = (
        parts["trait_hit"] * 0.25
        + parts["tool_hit"] * 0.25
        + parts["tool_forbid"] * 0.20
        + parts["rule_hit"] * 0.15
        + parts["ns_agreement"] * 0.10
        + parts["prompt_present"] * 0.05
    )
    return score, parts


def neurosymbolic_fitness(
    genome: TraitGenome,
    context: Dict[str, Any],
) -> FitnessResult:
    """
    Evaluate genome purely through neuro-symbolic scenario performance.

    context keys (optional):
      scenarios: List[NSScenario] or list of dicts
      trait_threshold: float
    """
    raw_scenarios = context.get("scenarios")
    scenarios: List[NSScenario]
    if not raw_scenarios:
        scenarios = DEFAULT_SCENARIOS
    else:
        scenarios = []
        for s in raw_scenarios:
            if isinstance(s, NSScenario):
                scenarios.append(s)
            elif isinstance(s, dict):
                scenarios.append(NSScenario(**{
                    k: v for k, v in s.items() if k in NSScenario.__dataclass_fields__
                }))

    thr = float(context.get("trait_threshold", 0.55))
    weighted_sum = 0.0
    weight_total = 0.0
    detail: Dict[str, float] = {}
    notes_parts: List[str] = []

    for sc in scenarios:
        decision = _reason_with_genome(genome, sc.metrics, sc.goal, trait_threshold=thr)
        sc_score, parts = score_scenario(decision, sc)
        weighted_sum += sc_score * sc.weight
        weight_total += sc.weight
        detail[f"sc:{sc.name}"] = round(sc_score, 4)
        if sc_score < 0.45:
            notes_parts.append(f"{sc.name}=weak")

    mean = weighted_sum / weight_total if weight_total else 0.0

    # Threshold calibration bonus: entropy_threshold near 0.7–0.85 is healthy
    ent_t = genome.get("entropy_threshold", 0.8)
    cal = max(0.0, 1.0 - abs(ent_t - 0.78) * 2.0)
    detail["threshold_calibration"] = round(cal, 4)

    # risk_aversion should be high if survival scenarios matter
    risk_av = genome.get("risk_aversion", 0.5)
    detail["risk_aversion"] = round(risk_av, 4)

    score = mean * 0.88 + cal * 0.12
    # slight learning_rate influence
    score *= 0.96 + 0.08 * genome.get("learning_rate", 0.1)

    return FitnessResult(
        genome_id=genome.id,
        score=max(0.0, min(1.5, score)),
        components=detail,
        notes=";".join(notes_parts) if notes_parts else "ns_ok",
    )


def hybrid_fitness(
    genome: TraitGenome,
    context: Dict[str, Any],
) -> FitnessResult:
    """
    Blend classic behavioral fitness with neuro-symbolic scenario fitness.

    context:
      ns_weight: float 0..1 (default 0.55) — share of NS fitness
      + all keys from default_fitness and neurosymbolic_fitness
    """
    ns_w = float(context.get("ns_weight", 0.55))
    ns_w = max(0.0, min(1.0, ns_w))
    classic_w = 1.0 - ns_w

    classic = default_fitness(genome, context)
    ns = neurosymbolic_fitness(genome, context)

    score = classic.score * classic_w + ns.score * ns_w
    components = {
        **{f"classic:{k}": v for k, v in classic.components.items()},
        **{f"ns:{k}": v for k, v in ns.components.items()},
        "blend_classic": round(classic.score * classic_w, 4),
        "blend_ns": round(ns.score * ns_w, 4),
    }
    return FitnessResult(
        genome_id=genome.id,
        score=max(0.0, min(1.5, score)),
        components=components,
        notes=f"hybrid ns_w={ns_w}; classic={classic.notes}; ns={ns.notes}",
    )


def evolve_traits_ns(
    generations: int = 10,
    population: int = 16,
    context: Optional[Dict[str, Any]] = None,
    seed: Optional[TraitGenome] = None,
    mode: str = "hybrid",  # hybrid | ns | classic
) -> Dict[str, Any]:
    """
    Run GA with neuro-symbolic-aware fitness.
    mode:
      hybrid  — blend default + NS (default)
      ns      — pure neurosymbolic_fitness
      classic — default_fitness only
    """
    from .genome import GenePool
    from .genetic import GeneticAlgorithm

    context = dict(context or {})
    if mode == "ns":
        fn = neurosymbolic_fitness
    elif mode == "classic":
        fn = default_fitness
    else:
        fn = hybrid_fitness

    pool = GenePool(size=population, seed_genome=seed)
    ga = GeneticAlgorithm(pool, fitness_fn=fn)
    best = ga.run(generations=generations, context=context)
    return {
        "best": best.to_dict(),
        "summary": pool.summary(),
        "history": ga.history,
        "fitness_mode": mode,
    }


def evaluate_genome_ns(
    genome: TraitGenome,
    scenarios: Optional[Sequence[NSScenario]] = None,
) -> Dict[str, Any]:
    """Detailed per-scenario breakdown for a single genome."""
    scenarios = list(scenarios) if scenarios else DEFAULT_SCENARIOS
    rows = []
    for sc in scenarios:
        decision = _reason_with_genome(genome, sc.metrics, sc.goal)
        sc_score, parts = score_scenario(decision, sc)
        rows.append({
            "scenario": sc.name,
            "score": round(sc_score, 4),
            "parts": parts,
            "traits": decision.traits,
            "tool": decision.tool,
            "rules": decision.applied_rules,
            "explanation": decision.explanation,
        })
    fr = neurosymbolic_fitness(genome, {"scenarios": scenarios})
    return {
        "genome_id": genome.id,
        "fitness": fr.score,
        "components": fr.components,
        "scenarios": rows,
    }
