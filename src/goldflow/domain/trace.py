"""DecisionTrace (PRD §9.2): auditable structured trace, not chain-of-thought.

Every state transition persists inputs, evidence ids, tool digests, derived
features, objections, versions, hashes and a concise rationale summary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from goldflow.domain.agents import ToolCallDigest
from goldflow.domain.values import EvidenceId, RunId, TargetId, TraceId


@dataclass(frozen=True, slots=True)
class ObjectionRef:
    kind: str
    severity: str
    statement: str


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    trace_id: TraceId
    run_id: RunId
    target_id: TargetId | None
    state_before: str
    state_after: str
    evidence_ids: tuple[EvidenceId, ...]
    tool_calls: tuple[ToolCallDigest, ...]
    derived_features: tuple[tuple[str, float], ...]
    objections: tuple[ObjectionRef, ...]
    scoring_model_version: str | None
    prompt_hashes: tuple[str, ...]
    model_ids: tuple[str, ...]
    rationale_summary: str
    created_at: datetime
    output_hash: str = field(default="")

    def with_output_hash(self) -> DecisionTrace:
        payload = json.dumps(
            {
                "run": str(self.run_id),
                "target": str(self.target_id) if self.target_id else None,
                "before": self.state_before,
                "after": self.state_after,
                "evidence": sorted(str(e) for e in self.evidence_ids),
                "features": sorted(self.derived_features),
                "model_version": self.scoring_model_version,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return DecisionTrace(
            trace_id=self.trace_id,
            run_id=self.run_id,
            target_id=self.target_id,
            state_before=self.state_before,
            state_after=self.state_after,
            evidence_ids=self.evidence_ids,
            tool_calls=self.tool_calls,
            derived_features=self.derived_features,
            objections=self.objections,
            scoring_model_version=self.scoring_model_version,
            prompt_hashes=self.prompt_hashes,
            model_ids=self.model_ids,
            rationale_summary=self.rationale_summary,
            created_at=self.created_at,
            output_hash=digest,
        )
