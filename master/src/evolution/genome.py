"""
Trait Genome — genetic representation of Evo-Psych cognitive parameters.

Each organism carries a genome of continuous + discrete genes that modulate
how LoopMem metrics map into traits (thresholds, prompt weights, biases).
"""

from __future__ import annotations

import json
import random
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Gene:
    """Single heritable parameter."""
    name: str
    value: float
    min_v: float = 0.0
    max_v: float = 1.0
    gene_type: str = "continuous"  # continuous | discrete | categorical
    categories: List[str] = field(default_factory=list)

    def clamp(self) -> None:
        if self.gene_type == "continuous":
            self.value = max(self.min_v, min(self.max_v, self.value))
        elif self.gene_type == "discrete":
            self.value = float(int(round(self.value)))
            self.value = max(self.min_v, min(self.max_v, self.value))

    def mutate(self, rate: float = 0.1, strength: float = 0.15) -> None:
        if random.random() > rate:
            return
        if self.gene_type == "categorical" and self.categories:
            self.value = float(random.randrange(len(self.categories)))
            return
        # Gaussian perturbation
        span = self.max_v - self.min_v
        self.value += random.gauss(0, strength * span)
        self.clamp()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Gene":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def default_trait_genes() -> List[Gene]:
    """
    Genes that control the Ghost Function thresholds and biases.
    Evolving these changes how the organism 'feels' under the same LoopMem.
    """
    return [
        Gene("entropy_threshold", 0.8, 0.4, 0.95),       # L5 → Divergent
        Gene("coupling_threshold", 0.05, 0.01, 0.20),    # L2 → Convergent
        Gene("core_survival_threshold", 0.1, 0.02, 0.35),# Core → Survival
        Gene("divergent_weight", 1.0, 0.2, 2.0),          # prompt intensity
        Gene("convergent_weight", 1.0, 0.2, 2.0),
        Gene("survival_weight", 1.0, 0.2, 2.0),
        Gene("u2_confidence_hi", 0.7, 0.5, 0.95),
        Gene("u2_confidence_lo", 0.2, 0.05, 0.4),
        Gene("exploration_bias", 0.5, 0.0, 1.0),          # speculative findings
        Gene("risk_aversion", 0.5, 0.0, 1.0),             # survival posture
        Gene("learning_rate", 0.1, 0.01, 0.5),            # fitness adaptation
        Gene("crossover_preference", 0.5, 0.0, 1.0),      # uniform vs single-point
    ]


@dataclass
class TraitGenome:
    """Full genotype for one cognitive organism."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generation: int = 0
    genes: Dict[str, Gene] = field(default_factory=dict)
    fitness: float = 0.0
    parent_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.genes:
            self.genes = {g.name: g for g in default_trait_genes()}

    def get(self, name: str, default: float = 0.0) -> float:
        g = self.genes.get(name)
        return g.value if g else default

    def thresholds(self) -> Dict[str, float]:
        return {
            "entropy": self.get("entropy_threshold", 0.8),
            "coupling": self.get("coupling_threshold", 0.05),
            "core_survival": self.get("core_survival_threshold", 0.1),
            "u2_hi": self.get("u2_confidence_hi", 0.7),
            "u2_lo": self.get("u2_confidence_lo", 0.2),
        }

    def mutate(self, rate: float = 0.15, strength: float = 0.12) -> "TraitGenome":
        child = self.clone()
        child.id = uuid.uuid4().hex[:12]
        child.generation = self.generation + 1
        child.parent_ids = [self.id]
        child.fitness = 0.0
        for gene in child.genes.values():
            gene.mutate(rate=rate, strength=strength)
        return child

    def clone(self) -> "TraitGenome":
        return TraitGenome(
            id=self.id,
            generation=self.generation,
            genes={k: Gene.from_dict(v.to_dict()) for k, v in self.genes.items()},
            fitness=self.fitness,
            parent_ids=list(self.parent_ids),
            metadata=deepcopy(self.metadata),
        )

    def crossover(self, other: "TraitGenome") -> "TraitGenome":
        """Uniform or single-point crossover based on gene preference average."""
        child = TraitGenome(generation=max(self.generation, other.generation) + 1)
        child.parent_ids = [self.id, other.id]
        pref = (self.get("crossover_preference") + other.get("crossover_preference")) / 2
        names = list(self.genes.keys())
        if pref > 0.5:
            # uniform
            for name in names:
                src = self if random.random() < 0.5 else other
                child.genes[name] = Gene.from_dict(src.genes[name].to_dict())
        else:
            # single-point
            point = random.randint(1, max(1, len(names) - 1))
            for i, name in enumerate(names):
                src = self if i < point else other
                child.genes[name] = Gene.from_dict(src.genes[name].to_dict())
        child.id = uuid.uuid4().hex[:12]
        return child

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "generation": self.generation,
            "fitness": self.fitness,
            "parent_ids": self.parent_ids,
            "genes": {k: v.to_dict() for k, v in self.genes.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TraitGenome":
        genes = {k: Gene.from_dict(v) for k, v in d.get("genes", {}).items()}
        return cls(
            id=d.get("id", uuid.uuid4().hex[:12]),
            generation=d.get("generation", 0),
            genes=genes,
            fitness=float(d.get("fitness", 0.0)),
            parent_ids=list(d.get("parent_ids") or []),
            metadata=dict(d.get("metadata") or {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class GenePool:
    """Population of TraitGenomes."""

    def __init__(self, size: int = 20, seed_genome: Optional[TraitGenome] = None):
        self.size = size
        base = seed_genome or TraitGenome()
        self.population: List[TraitGenome] = [base.clone() for _ in range(size)]
        for i, g in enumerate(self.population):
            if i > 0:
                # diversify initial population
                for gene in g.genes.values():
                    gene.mutate(rate=0.8, strength=0.25)
                g.id = uuid.uuid4().hex[:12]

    def best(self) -> TraitGenome:
        return max(self.population, key=lambda g: g.fitness)

    def mean_fitness(self) -> float:
        if not self.population:
            return 0.0
        return sum(g.fitness for g in self.population) / len(self.population)

    def summary(self) -> Dict[str, Any]:
        ranked = sorted(self.population, key=lambda g: -g.fitness)
        return {
            "size": len(self.population),
            "mean_fitness": self.mean_fitness(),
            "best_fitness": ranked[0].fitness if ranked else 0.0,
            "best_id": ranked[0].id if ranked else None,
            "generation_span": (
                min(g.generation for g in self.population),
                max(g.generation for g in self.population),
            ),
        }
