"""
CycleKernel Evolutionary Organism Layer
Genetic trait evolution · tool policy evolution · neuro-symbolic hybrid reasoning
"""

from .genome import TraitGenome, Gene, GenePool
from .genetic import GeneticAlgorithm, FitnessResult, evolve_traits
from .tool_evolution import ToolGenome, evolve_tool_policies, CodingEvolution
from .neurosymbolic import NeuroSymbolicReasoner, SymbolicRule, NeuralScore
from .ns_fitness import (
    neurosymbolic_fitness, hybrid_fitness, evolve_traits_ns,
    evaluate_genome_ns, DEFAULT_SCENARIOS, NSScenario,
)

__all__ = [
    "TraitGenome",
    "Gene",
    "GenePool",
    "GeneticAlgorithm",
    "FitnessResult",
    "evolve_traits",
    "ToolGenome",
    "evolve_tool_policies",
    "CodingEvolution",
    "NeuroSymbolicReasoner",
    "SymbolicRule",
    "NeuralScore",
    "neurosymbolic_fitness",
    "hybrid_fitness",
    "evolve_traits_ns",
    "evaluate_genome_ns",
    "DEFAULT_SCENARIOS",
    "NSScenario",
]
