"""Agent mesh contracts (PRD §7): agents are policies over the Evidence Store.

Agents emit structured artifacts; validated application services commit them.
No agent writes authoritative tables or sets a final score (PRD §5.2, §15.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from goldflow.domain.evidence import Evidence, EvidencePolarity
from goldflow.domain.planning import MeasurementProposal
from goldflow.domain.results import Result
from goldflow.domain.values import EvidenceId, RunId, SourceId, TargetId


class ObjectionKind(StrEnum):
    CONTAMINATION_ALTERNATIVE = "CONTAMINATION_ALTERNATIVE"
    NON_GOLD_LITHOLOGY = "NON_GOLD_LITHOLOGY"
    NO_TRANSPORT_PATH = "NO_TRANSPORT_PATH"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    FLOW_UNVERIFIED = "FLOW_UNVERIFIED"
    DATA_QUALITY = "DATA_QUALITY"
    SENSOR_LIMITATION = "SENSOR_LIMITATION"


class ObjectionSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class Objection:
    kind: ObjectionKind
    severity: ObjectionSeverity
    statement: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True, slots=True)
class Claim:
    statement: str
    polarity: EvidencePolarity
    evidence_ids: tuple[EvidenceId, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class AgentBudget:
    max_llm_calls: int
    max_tokens: int
    max_tool_calls: int


@dataclass(frozen=True, slots=True)
class AgentContext:
    run_id: RunId
    target_id: TargetId | None
    evidence_ids: tuple[EvidenceId, ...]
    source_snapshot_id: str
    budget: AgentBudget


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    agent_name: str
    claims: tuple[Claim, ...]
    proposed_evidence: tuple[Evidence, ...]
    objections: tuple[Objection, ...]
    next_actions: tuple[MeasurementProposal, ...]
    rationale_summary: str  # concise, source-grounded; never hidden chain-of-thought


@dataclass(frozen=True, slots=True)
class AgentError:
    agent_name: str
    code: str
    message: str


type AgentResult = Result[AgentArtifact, AgentError]


@dataclass(frozen=True, slots=True)
class ToolCallDigest:
    tool: str
    canonical_request: str
    response_ref: str  # artifact id or content hash, not raw payload
    status: str
    latency_ms: int
    source_id: SourceId | None = None
