"""
Decentralized Agent Consensus
=============================
Sub-agents cast weighted votes on proposals (tool choice, job approve,
genome promote, chain selection). No single agent is authoritative.

Protocols:
  majority     — simple count
  weighted     — role/mood-weighted shares
  unanimous    — all must approve
  quorum       — minimum participation + majority of voters
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ck.consensus")


class VoteValue(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    ABSTAIN = "abstain"


class ConsensusProtocol(str, Enum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"
    UNANIMOUS = "unanimous"
    QUORUM = "quorum"


# Default voting weight by agent role
ROLE_WEIGHTS: Dict[str, float] = {
    "reasoning": 1.2,
    "planning": 1.1,
    "research": 1.0,
    "coding": 1.0,
    "artifact": 0.9,
    "container": 0.9,
    "server": 0.8,
    "ops": 1.3,
    "human": 2.0,
}


@dataclass
class Vote:
    agent: str
    value: str
    weight: float = 1.0
    reason: str = ""
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Proposal:
    id: str
    type: str  # tool_execute | job_approve | genome_promote | chain_select | custom
    summary: str
    payload: Dict[str, Any] = field(default_factory=dict)
    protocol: str = ConsensusProtocol.WEIGHTED.value
    quorum: float = 0.5  # fraction of invited agents that must vote
    invited: List[str] = field(default_factory=list)
    votes: List[Vote] = field(default_factory=list)
    status: str = "open"  # open | approved | denied | expired
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    closed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class ConsensusEngine:
    def __init__(self, default_agents: Optional[List[str]] = None):
        self.default_agents = default_agents or [
            "reasoning",
            "coding",
            "artifact",
            "container",
            "server",
        ]
        self.proposals: Dict[str, Proposal] = {}

    def open_proposal(
        self,
        type: str,
        summary: str,
        payload: Optional[Dict[str, Any]] = None,
        protocol: str = ConsensusProtocol.WEIGHTED.value,
        invited: Optional[List[str]] = None,
        quorum: float = 0.5,
    ) -> Proposal:
        p = Proposal(
            id=uuid.uuid4().hex[:10],
            type=type,
            summary=summary,
            payload=dict(payload or {}),
            protocol=protocol,
            invited=list(invited or self.default_agents),
            quorum=quorum,
        )
        self.proposals[p.id] = p
        logger.info("proposal open id=%s type=%s protocol=%s", p.id, type, protocol)
        return p

    def cast_vote(
        self,
        proposal_id: str,
        agent: str,
        value: str,
        reason: str = "",
        weight: Optional[float] = None,
    ) -> Proposal:
        p = self.proposals.get(proposal_id)
        if not p:
            raise KeyError(f"proposal {proposal_id} not found")
        if p.status != "open":
            raise RuntimeError(f"proposal {proposal_id} is {p.status}")
        # replace prior vote from same agent
        p.votes = [v for v in p.votes if v.agent != agent]
        w = weight if weight is not None else ROLE_WEIGHTS.get(agent, 1.0)
        p.votes.append(
            Vote(agent=agent, value=value, weight=w, reason=reason)
        )
        return self.tally(proposal_id)

    def _auto_agent_votes(self, p: Proposal, mood: Optional[Dict[str, Any]] = None) -> None:
        """
        Heuristic decentralized votes from agent personas.
        Mood biases survival → deny risky; divergent → approve explore.
        """
        mood = mood or {}
        traits = list(mood.get("traits") or [])
        survival = any("Survival" in t for t in traits)
        divergent = any("Divergent" in t or "Creative" in t for t in traits)
        risky_types = {"tool_execute", "genome_promote"}
        for agent in p.invited:
            if any(v.agent == agent for v in p.votes):
                continue
            value = VoteValue.APPROVE.value
            reason = "default approve"
            if agent == "reasoning":
                value = VoteValue.APPROVE.value
                reason = "chain coherent"
            if agent == "server" and p.type in risky_types:
                value = VoteValue.ABSTAIN.value
                reason = "runtime neutral"
            if survival and p.type in ("genome_promote", "tool_execute"):
                if agent in ("container", "server", "artifact"):
                    value = VoteValue.DENY.value
                    reason = "survival lock — prefer stability"
            if divergent and p.type == "genome_promote" and agent in ("reasoning", "research"):
                value = VoteValue.APPROVE.value
                reason = "exploration bias"
            if p.type == "job_approve" and agent == "coding":
                value = VoteValue.APPROVE.value
                reason = "build path available"
            w = ROLE_WEIGHTS.get(agent, 1.0)
            p.votes.append(Vote(agent=agent, value=value, weight=w, reason=reason))

    def tally(self, proposal_id: str, auto_close: bool = True) -> Proposal:
        p = self.proposals[proposal_id]
        if p.status != "open":
            return p

        invited_n = max(1, len(p.invited))
        participated = {v.agent for v in p.votes}
        participation = len(participated & set(p.invited)) / invited_n

        approve_w = sum(v.weight for v in p.votes if v.value == VoteValue.APPROVE.value)
        deny_w = sum(v.weight for v in p.votes if v.value == VoteValue.DENY.value)
        abstain_w = sum(v.weight for v in p.votes if v.value == VoteValue.ABSTAIN.value)
        approve_n = sum(1 for v in p.votes if v.value == VoteValue.APPROVE.value)
        deny_n = sum(1 for v in p.votes if v.value == VoteValue.DENY.value)

        decided = False
        approved = False
        protocol = p.protocol

        if protocol == ConsensusProtocol.UNANIMOUS.value:
            if participation >= 1.0:
                decided = True
                approved = deny_n == 0 and approve_n > 0
        elif protocol == ConsensusProtocol.QUORUM.value:
            if participation >= p.quorum:
                decided = True
                approved = approve_n > deny_n
        elif protocol == ConsensusProtocol.MAJORITY.value:
            if participation >= p.quorum:
                decided = True
                approved = approve_n > deny_n
        else:  # weighted
            if participation >= p.quorum:
                decided = True
                approved = approve_w > deny_w

        p.result = {
            "participation": round(participation, 3),
            "approve_weight": round(approve_w, 3),
            "deny_weight": round(deny_w, 3),
            "abstain_weight": round(abstain_w, 3),
            "approve_count": approve_n,
            "deny_count": deny_n,
            "protocol": protocol,
            "decided": decided,
            "approved": approved if decided else None,
        }

        if auto_close and decided:
            p.status = "approved" if approved else "denied"
            p.closed_at = datetime.utcnow().isoformat()
            logger.info("proposal closed id=%s status=%s", p.id, p.status)
        return p

    def decide_with_agents(
        self,
        type: str,
        summary: str,
        payload: Optional[Dict[str, Any]] = None,
        protocol: str = ConsensusProtocol.WEIGHTED.value,
        mood: Optional[Dict[str, Any]] = None,
        invited: Optional[List[str]] = None,
    ) -> Proposal:
        """Open proposal, cast heuristic agent votes, tally, close."""
        p = self.open_proposal(
            type=type,
            summary=summary,
            payload=payload,
            protocol=protocol,
            invited=invited,
        )
        self._auto_agent_votes(p, mood=mood)
        return self.tally(p.id)

    def list_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        items = list(self.proposals.values())
        if status:
            items = [p for p in items if p.status == status]
        items.sort(key=lambda p: p.created_at, reverse=True)
        return [p.to_dict() for p in items]
