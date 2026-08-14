"""Hydrology domain: flow classification and the FlowGate (PRD §3).

The system is flowing-water-first. A target is field-eligible only when its
waterway segment carries verified, unexpired flow evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from goldflow.domain.results import Err, FlowVerificationError, Ok, Result
from goldflow.domain.values import (
    Probability,
    SourceId,
    WaterwayId,
    WaterwaySegmentId,
)


class FlowStatus(StrEnum):
    VERIFIED_PERENNIAL = "VERIFIED_PERENNIAL"
    VERIFIED_CURRENT = "VERIFIED_CURRENT"
    SEASONAL_EXPECTED = "SEASONAL_EXPECTED"
    EPHEMERAL = "EPHEMERAL"
    DRY = "DRY"
    UNKNOWN = "UNKNOWN"


FIELD_ELIGIBLE_STATUSES: frozenset[FlowStatus] = frozenset(
    {FlowStatus.VERIFIED_PERENNIAL, FlowStatus.VERIFIED_CURRENT}
)


class FlowEvidenceKind(StrEnum):
    OFFICIAL_LAYER = "OFFICIAL_LAYER"
    SPRING_DISCHARGE = "SPRING_DISCHARGE"
    HYDROMETRIC_STATION = "HYDROMETRIC_STATION"
    FIELD_OBSERVATION = "FIELD_OBSERVATION"
    REMOTE_SENSING = "REMOTE_SENSING"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@dataclass(frozen=True, slots=True)
class FlowObservation:
    segment_id: WaterwaySegmentId
    kind: FlowEvidenceKind
    status: FlowStatus
    confidence: Probability
    observed_at: datetime
    valid_until: datetime
    source_id: SourceId

    def is_current(self, at: datetime) -> bool:
        return self.observed_at <= at <= self.valid_until


@dataclass(frozen=True, slots=True)
class WaterwaySegment:
    id: WaterwaySegmentId
    waterway_id: WaterwayId
    name: str | None
    flow_status: FlowStatus
    flow_confidence: Probability
    flow_valid_until: datetime | None
    length_m: float


@dataclass(frozen=True, slots=True)
class FlowGatePass:
    segment_id: WaterwaySegmentId
    status: FlowStatus
    confidence: Probability
    valid_until: datetime


def verify_current_flow(
    observation: FlowObservation, at: datetime
) -> Result[FlowObservation, FlowVerificationError]:
    """An expired flow observation can never satisfy the current-flow gate (§18.2)."""
    if observation.status not in FIELD_ELIGIBLE_STATUSES:
        return Err(
            FlowVerificationError(
                code="FLOW_STATUS_NOT_ELIGIBLE",
                message=f"status {observation.status} not field-eligible",
                segment_id=str(observation.segment_id),
            )
        )
    if not observation.is_current(at):
        return Err(
            FlowVerificationError(
                code="FLOW_EVIDENCE_EXPIRED",
                message=(
                    f"observation valid until {observation.valid_until.isoformat()}, "
                    f"now {at.isoformat()}"
                ),
                segment_id=str(observation.segment_id),
            )
        )
    return Ok(observation)


DEFAULT_MIN_FLOW_CONFIDENCE = Probability(0.6)


def evaluate_flow_gate(
    segment: WaterwaySegment,
    observations: tuple[FlowObservation, ...],
    at: datetime,
    min_confidence: Probability = DEFAULT_MIN_FLOW_CONFIDENCE,
) -> Result[FlowGatePass, FlowVerificationError]:
    """FlowGate: highest-confidence current, field-eligible observation wins.

    Deterministic: ties broken by (confidence, observed_at, kind) ordering,
    invariant to input ordering.
    """
    current = [obs for obs in observations if isinstance(verify_current_flow(obs, at), Ok)]
    qualified = [obs for obs in current if obs.confidence.value >= min_confidence.value]
    if not qualified:
        return Err(
            FlowVerificationError(
                code="FLOW_GATE_FAILED",
                message="no current, confident flow evidence for segment",
                segment_id=str(segment.id),
            )
        )
    best = max(qualified, key=lambda o: (o.confidence.value, o.observed_at, o.kind.value))
    return Ok(
        FlowGatePass(
            segment_id=segment.id,
            status=best.status,
            confidence=best.confidence,
            valid_until=best.valid_until,
        )
    )
