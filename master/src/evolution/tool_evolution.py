"""
Tool Policy Evolution + Coding Algorithms
=========================================
Evolves ToolPolicy parameters (timeouts, concurrency, rate limits) via GA,
and uses a simple genetic-programming style coding algorithm to mutate
artifact templates / run strategies.
"""

from __future__ import annotations

import random
import textwrap
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Tool policy genome
# ---------------------------------------------------------------------------

@dataclass
class ToolGene:
    name: str
    value: float
    min_v: float
    max_v: float

    def mutate(self, rate: float = 0.2, strength: float = 0.15) -> None:
        if random.random() > rate:
            return
        span = self.max_v - self.min_v
        self.value += random.gauss(0, strength * span)
        self.value = max(self.min_v, min(self.max_v, self.value))


@dataclass
class ToolGenome:
    """Evolvable policy parameters for one tool."""
    tool: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    generation: int = 0
    fitness: float = 0.0
    genes: Dict[str, ToolGene] = field(default_factory=dict)

    def __post_init__(self):
        if not self.genes:
            self.genes = {
                "timeout_sec": ToolGene("timeout_sec", 30.0, 5.0, 120.0),
                "max_retries": ToolGene("max_retries", 1.0, 0.0, 4.0),
                "max_concurrency": ToolGene("max_concurrency", 4.0, 1.0, 16.0),
                "rate_limit_per_min": ToolGene("rate_limit_per_min", 20.0, 2.0, 120.0),
                "circuit_fail_threshold": ToolGene("circuit_fail_threshold", 5.0, 2.0, 15.0),
                "circuit_cooldown_sec": ToolGene("circuit_cooldown_sec", 60.0, 10.0, 180.0),
            }

    def get(self, name: str) -> float:
        return self.genes[name].value

    def to_policy_dict(self) -> Dict[str, Any]:
        return {
            "timeout_sec": self.get("timeout_sec"),
            "max_retries": int(round(self.get("max_retries"))),
            "max_concurrency": int(round(self.get("max_concurrency"))),
            "rate_limit_per_min": int(round(self.get("rate_limit_per_min"))),
            "circuit_fail_threshold": int(round(self.get("circuit_fail_threshold"))),
            "circuit_cooldown_sec": self.get("circuit_cooldown_sec"),
        }

    def mutate(self, rate: float = 0.25) -> "ToolGenome":
        child = ToolGenome(tool=self.tool, generation=self.generation + 1)
        child.genes = {
            k: ToolGene(v.name, v.value, v.min_v, v.max_v)
            for k, v in self.genes.items()
        }
        for g in child.genes.values():
            g.mutate(rate=rate)
        return child

    def crossover(self, other: "ToolGenome") -> "ToolGenome":
        child = ToolGenome(tool=self.tool, generation=max(self.generation, other.generation) + 1)
        for name in self.genes:
            src = self if random.random() < 0.5 else other
            g = src.genes[name]
            child.genes[name] = ToolGene(g.name, g.value, g.min_v, g.max_v)
        return child

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "id": self.id,
            "generation": self.generation,
            "fitness": self.fitness,
            "policy": self.to_policy_dict(),
            "genes": {k: asdict(v) for k, v in self.genes.items()},
        }


def tool_policy_fitness(genome: ToolGenome, context: Dict[str, Any]) -> float:
    """
    context:
      success_rate, avg_latency_sec, timeout_rate, reject_rate
    Prefer high success, low timeout, moderate concurrency.
    """
    success = float(context.get("success_rate", 0.5))
    latency = float(context.get("avg_latency_sec", 5.0))
    timeout_rate = float(context.get("timeout_rate", 0.1))
    reject_rate = float(context.get("reject_rate", 0.05))

    timeout_gene = genome.get("timeout_sec")
    # penalize if timeout_gene is much lower than observed latency needs
    latency_fit = 1.0 - min(1.0, abs(timeout_gene - max(latency * 2, 5.0)) / 60.0)
    conc = genome.get("max_concurrency")
    conc_fit = 1.0 - abs(conc - 4.0) / 12.0

    score = (
        success * 0.45
        + (1.0 - timeout_rate) * 0.20
        + (1.0 - reject_rate) * 0.10
        + latency_fit * 0.15
        + max(0.0, conc_fit) * 0.10
    )
    return max(0.0, min(1.2, score))


def evolve_tool_policies(
    tools: Optional[List[str]] = None,
    generations: int = 8,
    population: int = 10,
    context_by_tool: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Evolve a ToolGenome population independently per tool name.
    Returns best policy per tool.
    """
    tools = tools or ["research", "scrape", "coding", "pipeline", "terminal_execute"]
    context_by_tool = context_by_tool or {}
    results = {}

    for tool in tools:
        pop = [ToolGenome(tool=tool) for _ in range(population)]
        for i, g in enumerate(pop):
            if i:
                g = g.mutate(rate=0.9)
                pop[i] = g

        history = []
        for _ in range(generations):
            ctx = context_by_tool.get(tool, {})
            for g in pop:
                g.fitness = tool_policy_fitness(g, ctx)
            pop.sort(key=lambda x: -x.fitness)
            history.append({"best": pop[0].fitness, "mean": sum(p.fitness for p in pop) / len(pop)})
            elites = pop[:2]
            next_pop = [deepcopy(e) for e in elites]
            while len(next_pop) < population:
                p1, p2 = random.sample(pop[: max(3, population // 2)], 2)
                child = p1.crossover(p2).mutate()
                next_pop.append(child)
            pop = next_pop

        for g in pop:
            g.fitness = tool_policy_fitness(g, context_by_tool.get(tool, {}))
        pop.sort(key=lambda x: -x.fitness)
        results[tool] = {
            "best": pop[0].to_dict(),
            "history": history,
        }
    return results


# ---------------------------------------------------------------------------
# Coding evolution (genetic programming–lite for artifact templates)
# ---------------------------------------------------------------------------

# Primitive building blocks the coding algorithm recombines
CODE_PRIMES = [
    "print('CycleKernel artifact executing')",
    "result = {'ok': True}",
    "result['genome'] = GENOME_ID",
    "result['goal'] = GOAL",
    "for i in range(3): result.setdefault('steps', []).append(i)",
    "assert result.get('ok') is True",
    "import json; print(json.dumps(result))",
]


@dataclass
class CodeIndividual:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    generation: int = 0
    lines: List[str] = field(default_factory=list)
    fitness: float = 0.0

    def __post_init__(self):
        if not self.lines:
            # random initial program of 3–6 primes
            k = random.randint(3, 6)
            self.lines = random.sample(CODE_PRIMES, k=min(k, len(CODE_PRIMES)))

    def render(self, goal: str = "evolve", genome_id: str = "n/a") -> str:
        body = "\n    ".join(self.lines)
        return textwrap.dedent(f'''\
            """Auto-evolved artifact gen={self.generation} id={self.id}"""
            GENOME_ID = {genome_id!r}
            GOAL = {goal!r}
            def main():
                {body}
                return 0
            if __name__ == "__main__":
                raise SystemExit(main())
            ''')

    def mutate(self, rate: float = 0.3) -> "CodeIndividual":
        child = CodeIndividual(generation=self.generation + 1, lines=list(self.lines))
        if random.random() < rate and child.lines:
            # swap one line
            idx = random.randrange(len(child.lines))
            child.lines[idx] = random.choice(CODE_PRIMES)
        if random.random() < rate * 0.5 and len(child.lines) < 8:
            child.lines.append(random.choice(CODE_PRIMES))
        if random.random() < rate * 0.3 and len(child.lines) > 2:
            child.lines.pop(random.randrange(len(child.lines)))
        if random.random() < rate * 0.4 and len(child.lines) > 1:
            i, j = random.sample(range(len(child.lines)), 2)
            child.lines[i], child.lines[j] = child.lines[j], child.lines[i]
        return child

    def crossover(self, other: "CodeIndividual") -> "CodeIndividual":
        if not self.lines or not other.lines:
            return self.mutate(rate=1.0)
        point = random.randint(1, min(len(self.lines), len(other.lines)))
        lines = self.lines[:point] + other.lines[point:]
        return CodeIndividual(generation=max(self.generation, other.generation) + 1, lines=lines)


def code_fitness(indiv: CodeIndividual) -> float:
    """Static fitness: diversity, length balance, presence of result + print."""
    joined = "\n".join(indiv.lines)
    score = 0.4
    if "result" in joined:
        score += 0.25
    if "print" in joined:
        score += 0.15
    if "GOAL" in joined or "GENOME" in joined:
        score += 0.1
    # prefer 3–6 lines
    n = len(indiv.lines)
    score += max(0.0, 0.1 - abs(n - 4) * 0.03)
    # diversity
    score += 0.05 * (len(set(indiv.lines)) / max(1, n))
    return min(1.0, score)


class CodingEvolution:
    """Evolve code templates that the CodingAgent can emit."""

    def __init__(self, population: int = 12):
        self.population = [CodeIndividual() for _ in range(population)]

    def step(self) -> CodeIndividual:
        for ind in self.population:
            ind.fitness = code_fitness(ind)
        self.population.sort(key=lambda x: -x.fitness)
        elites = self.population[:2]
        next_pop = [CodeIndividual(generation=e.generation, lines=list(e.lines)) for e in elites]
        for e in next_pop:
            e.fitness = e.fitness  # keep
        while len(next_pop) < len(self.population):
            p1, p2 = random.sample(self.population[:5], 2)
            child = p1.crossover(p2).mutate()
            next_pop.append(child)
        self.population = next_pop
        for ind in self.population:
            ind.fitness = code_fitness(ind)
        self.population.sort(key=lambda x: -x.fitness)
        return self.population[0]

    def run(self, generations: int = 15) -> Dict[str, Any]:
        history = []
        best = self.population[0]
        for g in range(generations):
            best = self.step()
            history.append({"gen": g, "best_fitness": best.fitness, "lines": len(best.lines)})
        return {
            "best_id": best.id,
            "best_fitness": best.fitness,
            "source": best.render(goal="evolved-artifact", genome_id=best.id),
            "history": history,
        }
