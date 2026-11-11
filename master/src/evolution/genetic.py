"""
Genetic Algorithm engine for trait evolution.

Fitness is derived from closed-loop feedback signals:
  - task success rate
  - mood stability / appropriate trait activation
  - tool-call efficiency
  - survival under low-core conditions
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .genome import GenePool, TraitGenome


@dataclass
class FitnessResult:
    genome_id: str
    score: float
    components: Dict[str, float] = field(default_factory=dict)
    notes: str = ""


FitnessFn = Callable[[TraitGenome, Dict[str, Any]], FitnessResult]


def default_fitness(genome: TraitGenome, context: Dict[str, Any]) -> FitnessResult:
    """
    Heuristic fitness when live feedback is sparse.

    context keys (all optional):
      success_rate: float 0..1
      tool_efficiency: float 0..1   (successes / calls)
      mood_alignment: float 0..1   (did traits match task needs)
      risk_events: int             (penalized)
      novelty: float 0..1          (reward exploration if bias high)
    """
    success = float(context.get("success_rate", 0.5))
    efficiency = float(context.get("tool_efficiency", 0.5))
    alignment = float(context.get("mood_alignment", 0.5))
    risk_events = int(context.get("risk_events", 0))
    novelty = float(context.get("novelty", 0.3))

    explore = genome.get("exploration_bias", 0.5)
    risk_av = genome.get("risk_aversion", 0.5)

    # Reward matching bias to outcomes
    explore_term = 1.0 - abs(explore - novelty)
    risk_term = 1.0 / (1.0 + risk_events * (0.5 + risk_av))

    # Prefer moderate thresholds (avoid extremes that never fire / always fire)
    ent_t = genome.get("entropy_threshold", 0.8)
    threshold_balance = 1.0 - abs(ent_t - 0.75) * 1.5
    threshold_balance = max(0.0, min(1.0, threshold_balance))

    components = {
        "success": success * 0.35,
        "efficiency": efficiency * 0.20,
        "alignment": alignment * 0.20,
        "explore_fit": explore_term * 0.10,
        "risk": risk_term * 0.10,
        "threshold_balance": threshold_balance * 0.05,
    }
    score = sum(components.values())
    # learning_rate gene slightly boosts score variance absorption
    score *= 0.95 + 0.1 * genome.get("learning_rate", 0.1)
    return FitnessResult(
        genome_id=genome.id,
        score=max(0.0, min(1.5, score)),
        components=components,
    )


class GeneticAlgorithm:
    """
    Classic generational GA:
      evaluate → select → crossover → mutate → replace
    """

    def __init__(
        self,
        pool: GenePool,
        fitness_fn: Optional[FitnessFn] = None,
        elite_count: int = 2,
        tournament_k: int = 3,
        mutation_rate: float = 0.18,
        mutation_strength: float = 0.12,
        crossover_rate: float = 0.7,
    ):
        self.pool = pool
        self.fitness_fn = fitness_fn or default_fitness
        self.elite_count = elite_count
        self.tournament_k = tournament_k
        self.mutation_rate = mutation_rate
        self.mutation_strength = mutation_strength
        self.crossover_rate = crossover_rate
        self.history: List[Dict[str, Any]] = []

    def evaluate(self, context: Optional[Dict[str, Any]] = None) -> List[FitnessResult]:
        context = context or {}
        results = []
        for g in self.pool.population:
            # allow per-genome context override
            ctx = {**context, **(g.metadata.get("fitness_context") or {})}
            fr = self.fitness_fn(g, ctx)
            g.fitness = fr.score
            results.append(fr)
        return results

    def tournament_select(self) -> TraitGenome:
        contenders = random.sample(
            self.pool.population,
            min(self.tournament_k, len(self.pool.population)),
        )
        return max(contenders, key=lambda g: g.fitness)

    def step(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """One generation."""
        self.evaluate(context)
        ranked = sorted(self.pool.population, key=lambda g: -g.fitness)
        elites = [g.clone() for g in ranked[: self.elite_count]]

        next_pop: List[TraitGenome] = elites
        while len(next_pop) < self.pool.size:
            p1 = self.tournament_select()
            if random.random() < self.crossover_rate:
                p2 = self.tournament_select()
                child = p1.crossover(p2)
            else:
                child = p1.clone()
                child.id = __import__("uuid").uuid4().hex[:12]
                child.generation = p1.generation + 1
                child.parent_ids = [p1.id]
            child = child.mutate(rate=self.mutation_rate, strength=self.mutation_strength)
            next_pop.append(child)

        self.pool.population = next_pop[: self.pool.size]
        summary = self.pool.summary()
        self.history.append(summary)
        return summary

    def run(self, generations: int = 10, context: Optional[Dict[str, Any]] = None) -> TraitGenome:
        for _ in range(generations):
            self.step(context)
        self.evaluate(context)
        return self.pool.best()


def evolve_traits(
    generations: int = 10,
    population: int = 16,
    context: Optional[Dict[str, Any]] = None,
    seed: Optional[TraitGenome] = None,
) -> Dict[str, Any]:
    """Convenience entry: run GA and return best genome + history."""
    pool = GenePool(size=population, seed_genome=seed)
    ga = GeneticAlgorithm(pool)
    best = ga.run(generations=generations, context=context or {})
    return {
        "best": best.to_dict(),
        "summary": pool.summary(),
        "history": ga.history,
    }


# ---------------------------------------------------------------------------
# Bridge: apply evolved genome to trait mapping thresholds
# ---------------------------------------------------------------------------

def map_metrics_with_genome(metrics: Dict[str, Any], genome: TraitGenome) -> Dict[str, Any]:
    """
    Neuro-symbolic style: symbolic rules with evolved numeric thresholds.
    Returns a cognitive state dict compatible with CognitiveBridge.
    """
    th = genome.thresholds()
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    l2 = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    l5 = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    u2 = float(metrics.get("U2", 0.0))

    traits: List[str] = []
    prompts: List[str] = []
    mood = "neutral"
    explanation = "LoopMem within nominal bounds."

    div_w = genome.get("divergent_weight", 1.0)
    con_w = genome.get("convergent_weight", 1.0)
    sur_w = genome.get("survival_weight", 1.0)

    if l5 > th["entropy"]:
        traits.append("Creative/Divergent")
        intensity = "strongly " if div_w > 1.2 else ""
        prompts.append(
            f"SYSTEM OVERRIDE [HIGH ENTROPY×{div_w:.2f}]: {intensity}Prioritize divergent ideation, "
            "novel analogies, exploratory branching."
        )
        mood = "divergent"
        explanation = "Current State: High Entropy — Expect Divergent Answers"

    if l2 > th["coupling"]:
        traits.append("Analytical/Convergent")
        prompts.append(
            f"SYSTEM OVERRIDE [HIGH COUPLING×{con_w:.2f}]: Enforce rigorous logical chaining "
            "and evidence-bound reasoning."
        )
        mood = "balanced-tension" if mood == "divergent" else "convergent"
        explanation = (
            "Current State: High Coupling — Expect Analytical Precision"
            if mood != "balanced-tension"
            else "Current State: High Entropy + High Coupling — Balanced Tension"
        )

    if core < th["core_survival"]:
        traits.append("Survival/Conservation")
        prompts.append(
            f"SYSTEM OVERRIDE [LOW CORE×{sur_w:.2f}]: Conservation protocols. "
            "Minimize risk; prefer stable known solutions."
        )
        mood = "survival"
        explanation = "Current State: Low Core — Survival Protocols Active"

    if u2 > th["u2_hi"]:
        traits.append("High-Confidence")
    elif u2 < th["u2_lo"]:
        traits.append("Exploratory-Uncertainty")

    if genome.get("exploration_bias", 0.5) > 0.7 and "Creative/Divergent" not in traits:
        if random.random() < genome.get("exploration_bias", 0.5) * 0.3:
            traits.append("Speculative-Probe")

    if not traits:
        traits.append("Neutral-Baseline")

    return {
        "mood": mood,
        "traits": traits,
        "system_prompt_override": "\n\n".join(prompts),
        "entropy": l5,
        "coupling": l2,
        "core": core,
        "genome_id": genome.id,
        "genome_generation": genome.generation,
        "thresholds_used": th,
        "explanation": explanation,
    }
