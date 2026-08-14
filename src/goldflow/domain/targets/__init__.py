"""ProspectTarget aggregate and state machines (PRD §8).

Transitions are validated pure functions; invalid transitions return typed
errors. FIELD_READY strictly requires a FlowGate pass plus guardrail clearance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from goldflow.domain.hydrology import FlowGatePass
from goldflow.domain.results import Err, Ok, Result, ValidationError
from goldflow.domain.values import (
    Point2039,
    Score,
    TargetId,
    WaterwaySegmentId,
)


class TargetState(StrEnum):
    CANDIDATE = "CANDIDATE"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    RESEARCH_READY = "RESEARCH_READY"
    FIELD_READY = "FIELD_READY"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    BLOCKED_NO_FLOW = "BLOCKED_NO_FLOW"
    BLOCKED_SAFETY = "BLOCKED_SAFETY"
    BLOCKED_LEGAL = "BLOCKED_LEGAL"
    VALIDATED_POSITIVE = "VALIDATED_POSITIVE"
    VALIDATED_NEGATIVE = "VALIDATED_NEGATIVE"
    ARCHIVED = "ARCHIVED"


class RunState(StrEnum):
    CREATED = "CREATED"
    DISCOVERING = "DISCOVERING"
    INGESTING = "INGESTING"
    NORMALIZING = "NORMALIZING"
    ANALYZING = "ANALYZING"
    CRITIQUING = "CRITIQUING"
    SCORING = "SCORING"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.DISCOVERING, RunState.CANCELLED, RunState.FAILED}),
    RunState.DISCOVERING: frozenset({RunState.INGESTING, RunState.CANCELLED, RunState.FAILED}),
    RunState.INGESTING: frozenset({RunState.NORMALIZING, RunState.CANCELLED, RunState.FAILED}),
    RunState.NORMALIZING: frozenset({RunState.ANALYZING, RunState.CANCELLED, RunState.FAILED}),
    RunState.ANALYZING: frozenset({RunState.CRITIQUING, RunState.CANCELLED, RunState.FAILED}),
    RunState.CRITIQUING: frozenset({RunState.SCORING, RunState.CANCELLED, RunState.FAILED}),
    RunState.SCORING: frozenset({RunState.PUBLISHING, RunState.CANCELLED, RunState.FAILED}),
    RunState.PUBLISHING: frozenset({RunState.COMPLETED, RunState.FAILED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


def advance_run(current: RunState, to: RunState) -> Result[RunState, ValidationError]:
    if to in _RUN_TRANSITIONS[current]:
        return Ok(to)
    return Err(
        ValidationError(
            code="INVALID_RUN_TRANSITION",
            message=f"{current} -> {to} not allowed",
        )
    )


class Actionability(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    SAMPLE_ALLOWED_UNKNOWN = "SAMPLE_ALLOWED_UNKNOWN"
    PERMIT_REQUIRED = "PERMIT_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ProspectTarget:
    id: TargetId
    waterway_segment_id: WaterwaySegmentId
    location: Point2039
    state: TargetState
    score: Score | None = None
    uncertainty: float | None = None
    actionability: Actionability = Actionability.OBSERVE_ONLY


_TARGET_TRANSITIONS: dict[TargetState, frozenset[TargetState]] = {
    TargetState.CANDIDATE: frozenset(
        {
            TargetState.NEEDS_EVIDENCE,
            TargetState.RESEARCH_READY,
            TargetState.BLOCKED_NO_FLOW,
            TargetState.ARCHIVED,
        }
    ),
    TargetState.NEEDS_EVIDENCE: frozenset(
        {TargetState.RESEARCH_READY, TargetState.BLOCKED_NO_FLOW, TargetState.ARCHIVED}
    ),
    TargetState.RESEARCH_READY: frozenset(
        {
            TargetState.FIELD_READY,
            TargetState.OBSERVATION_ONLY,
            TargetState.NEEDS_EVIDENCE,
            TargetState.BLOCKED_NO_FLOW,
            TargetState.BLOCKED_SAFETY,
            TargetState.BLOCKED_LEGAL,
            TargetState.ARCHIVED,
        }
    ),
    TargetState.FIELD_READY: frozenset(
        {
            TargetState.VALIDATED_POSITIVE,
            TargetState.VALIDATED_NEGATIVE,
            TargetState.BLOCKED_NO_FLOW,
            TargetState.BLOCKED_SAFETY,
            TargetState.BLOCKED_LEGAL,
            TargetState.OBSERVATION_ONLY,
            TargetState.ARCHIVED,
        }
    ),
    TargetState.OBSERVATION_ONLY: frozenset(
        {
            TargetState.FIELD_READY,
            TargetState.RESEARCH_READY,
            TargetState.VALIDATED_POSITIVE,
            TargetState.VALIDATED_NEGATIVE,
            TargetState.ARCHIVED,
        }
    ),
    TargetState.BLOCKED_NO_FLOW: frozenset({TargetState.RESEARCH_READY, TargetState.ARCHIVED}),
    TargetState.BLOCKED_SAFETY: frozenset({TargetState.RESEARCH_READY, TargetState.ARCHIVED}),
    TargetState.BLOCKED_LEGAL: frozenset({TargetState.RESEARCH_READY, TargetState.ARCHIVED}),
    TargetState.VALIDATED_POSITIVE: frozenset({TargetState.ARCHIVED, TargetState.FIELD_READY}),
    TargetState.VALIDATED_NEGATIVE: frozenset({TargetState.ARCHIVED, TargetState.RESEARCH_READY}),
    TargetState.ARCHIVED: frozenset(),
}


def transition_target(
    target: ProspectTarget, to: TargetState
) -> Result[ProspectTarget, ValidationError]:
    if to in _TARGET_TRANSITIONS[target.state]:
        return Ok(replace(target, state=to))
    return Err(
        ValidationError(
            code="INVALID_TARGET_TRANSITION",
            message=f"{target.state} -> {to} not allowed for {target.id}",
        )
    )


def promote_to_field_ready(
    target: ProspectTarget,
    flow_pass: FlowGatePass,
    guardrails_clear: bool,
) -> Result[ProspectTarget, ValidationError]:
    """FIELD_READY requires the segment's FlowGate pass and guardrail clearance.

    The flow pass must belong to the target's own segment (§18.2: a FIELD_READY
    target references exactly one active WaterwaySegment that passed FlowGate).
    """
    if flow_pass.segment_id != target.waterway_segment_id:
        return Err(
            ValidationError(
                code="FLOW_PASS_SEGMENT_MISMATCH",
                message="flow gate pass does not belong to target segment",
            )
        )
    if not guardrails_clear:
        return Err(
            ValidationError(
                code="GUARDRAILS_NOT_CLEAR",
                message="guardrail block prevents FIELD_READY",
            )
        )
    return transition_target(target, TargetState.FIELD_READY)
