"""FlowGate invariants (PRD §3, §18.2/§18.3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from goldflow.domain.hydrology import (
    FlowEvidenceKind,
    FlowObservation,
    FlowStatus,
    WaterwaySegment,
    evaluate_flow_gate,
    verify_current_flow,
)
from goldflow.domain.results import Err, Ok
from goldflow.domain.values import (
    Probability,
    SourceId,
    WaterwayId,
    WaterwaySegmentId,
    utc_now,
)


def _observation(
    status: FlowStatus = FlowStatus.VERIFIED_CURRENT,
    confidence: float = 0.8,
    valid_for_days: int = 30,
) -> FlowObservation:
    now = utc_now()
    return FlowObservation(
        segment_id=WaterwaySegmentId(uuid4()),
        kind=FlowEvidenceKind.SPRING_DISCHARGE,
        status=status,
        confidence=Probability(confidence),
        observed_at=now - timedelta(days=1),
        valid_until=now + timedelta(days=valid_for_days),
        source_id=SourceId(uuid4()),
    )


def _segment(segment_id: WaterwaySegmentId) -> WaterwaySegment:
    return WaterwaySegment(
        id=segment_id,
        waterway_id=WaterwayId(uuid4()),
        name="test",
        flow_status=FlowStatus.VERIFIED_CURRENT,
        flow_confidence=Probability(0.8),
        flow_valid_until=utc_now() + timedelta(days=30),
        length_m=1000.0,
    )


def test_expired_flow_never_passes_current_gate() -> None:
    observation = _observation()
    expired = replace(observation, valid_until=utc_now() - timedelta(seconds=1))
    result = verify_current_flow(expired, utc_now())
    assert isinstance(result, Err)
    assert result.error.code == "FLOW_EVIDENCE_EXPIRED"


def test_dry_or_unknown_status_blocked() -> None:
    for status in (
        FlowStatus.DRY,
        FlowStatus.UNKNOWN,
        FlowStatus.EPHEMERAL,
        FlowStatus.SEASONAL_EXPECTED,
    ):
        result = verify_current_flow(_observation(status=status), utc_now())
        assert isinstance(result, Err)


def test_gate_requires_confident_observation() -> None:
    observation = _observation(confidence=0.3)
    segment = _segment(observation.segment_id)
    result = evaluate_flow_gate(segment, (observation,), utc_now())
    assert isinstance(result, Err)
    assert result.error.code == "FLOW_GATE_FAILED"


def test_gate_passes_with_valid_observation() -> None:
    observation = _observation()
    segment = _segment(observation.segment_id)
    result = evaluate_flow_gate(segment, (observation,), utc_now())
    assert isinstance(result, Ok)
    assert result.value.segment_id == segment.id


def test_gate_invariant_to_observation_order() -> None:
    strong = _observation(confidence=0.9)
    weak = replace(_observation(confidence=0.65), segment_id=strong.segment_id)
    segment = _segment(strong.segment_id)
    forward = evaluate_flow_gate(segment, (strong, weak), utc_now())
    backward = evaluate_flow_gate(segment, (weak, strong), utc_now())
    assert isinstance(forward, Ok) and isinstance(backward, Ok)
    assert forward.value == backward.value
