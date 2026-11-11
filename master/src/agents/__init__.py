"""CycleKernel sub-agents — reasoning, coding, artifact, container, server + research/planning."""

from .base import BaseAgent, AgentResult
from .reasoning import ReasoningAgent
from .coding import CodingAgent
from .artifact import ArtifactAgent
from .container import ContainerAgent
from .server import ServerHostAgent
from .spawn import (
    AGENT_TYPES,
    list_agents,
    get_agent,
    spawn,
    spawn_many,
    sandbox_pipeline,
)

try:
    from .research import ResearchAgent
except Exception:  # pragma: no cover
    ResearchAgent = None  # type: ignore
try:
    from .planning import PlanningAgent
except Exception:  # pragma: no cover
    PlanningAgent = None  # type: ignore

__all__ = [
    "BaseAgent",
    "AgentResult",
    "ReasoningAgent",
    "CodingAgent",
    "ArtifactAgent",
    "ContainerAgent",
    "ServerHostAgent",
    "ResearchAgent",
    "PlanningAgent",
    "AGENT_TYPES",
    "list_agents",
    "get_agent",
    "spawn",
    "spawn_many",
    "sandbox_pipeline",
]
