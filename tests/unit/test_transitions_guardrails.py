"""State machine + guardrail invariants (PRD §8, §15, §18.2)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from goldflow.domain.guardrails import GuardrailInputs, evaluate_guardrails
from goldflow.domain.hydrology import (
    FlowEvidenceKind,
    FlowGatePass,
    FlowObservation,
    FlowStatus,
    WaterwaySegment,
)
from goldflow.domain.results import Err, Ok
from goldflow.domain.targets import (
    Actionability,
    ProspectTarget,
    RunState,
    TargetState,
    advance_run,
    promote_to_field_ready,
    transition_target,
)
from goldflow.domain.values import (
    Point2039,
    Probability,
    SourceId,
    TargetId,
    WaterwayId,
    WaterwaySegmentId,
    utc_now,
)


def _target(state: TargetState = TargetState.RESEARCH_READY) -> ProspectTarget:
    return ProspectTarget(
        id=TargetId(uuid4()),
        waterway_segment_id=WaterwaySegmentId(uuid4()),
        location=Point2039(200000.0, 750000.0),
        state=state,
    )


def _segment(flow: FlowStatus = FlowStatus.VERIFIED_CURRENT) -> WaterwaySegment:
    return WaterwaySegment(
        id=WaterwaySegmentId(uuid4()),
        waterway_id=WaterwayId(uuid4()),
        name="seg",
        flow_status=flow,
        flow_confidence=Probability(0.8),
        flow_valid_until=utc_now() + timedelta(days=10),
        length_m=2000.0,
    )


def _observation(segment: WaterwaySegment) -> FlowObservation:
    return FlowObservation(
        segment_id=segment.id,
        kind=FlowEvidenceKind.SPRING_DISCHARGE,
        status=FlowStatus.VERIFIED_CURRENT,
        confidence=Probability(0.8),
        observed_at=utc_now() - timedelta(days=1),
        valid_until=utc_now() + timedelta(days=10),
        source_id=SourceId(uuid4()),
    )


def test_run_state_machine_rejects_skips() -> None:
    assert isinstance(advance_run(RunState.CREATED, RunState.SCORING), Err)
    assert isinstance(advance_run(RunState.CREATED, RunState.DISCOVERING), Ok)
    assert isinstance(advance_run(RunState.COMPLETED, RunState.ANALYZING), Err)


def test_field_ready_requires_matching_segment_flow_pass() -> None:
    target = _target()
    foreign_pass = FlowGatePass(
        segment_id=WaterwaySegmentId(uuid4()),  # not the target's segment
        status=FlowStatus.VERIFIED_CURRENT,
        confidence=Probability(0.9),
        valid_until=utc_now() + timedelta(days=5),
    )
    result = promote_to_field_ready(target, foreign_pass, True)
    assert isinstance(result, Err)
    assert result.error.code == "FLOW_PASS_SEGMENT_MISMATCH"


def test_field_ready_requires_guardrail_clearance() -> None:
    target = _target()
    matching_pass = FlowGatePass(
        segment_id=target.waterway_segment_id,
        status=FlowStatus.VERIFIED_CURRENT,
        confidence=Probability(0.9),
        valid_until=utc_now() + timedelta(days=5),
    )
    blocked = promote_to_field_ready(target, matching_pass, False)
    assert isinstance(blocked, Err)
    allowed = promote_to_field_ready(target, matching_pass, True)
    assert isinstance(allowed, Ok)
    assert allowed.value.state is TargetState.FIELD_READY


def test_archived_is_terminal() -> None:
    archived = _target(TargetState.ARCHIVED)
    for state in TargetState:
        if state is TargetState.ARCHIVED:
            continue
        assert isinstance(transition_target(archived, state), Err)


def test_water_quality_alert_blocks_field_action() -> None:
    segment = _segment()
    verdict = evaluate_guardrails(
        GuardrailInputs(
            segment=segment,
            flow_observations=(_observation(segment),),
            now=utc_now(),
            water_quality_alert=True,
        )
    )
    assert verdict.actionability is Actionability.BLOCKED
    assert not verdict.field_clear
    # scientific ranking survives: flow pass still present (§18.2)
    assert verdict.flow_pass is not None


def test_no_flow_evidence_blocks_gate_but_mining_review_always_present() -> None:
    segment = _segment(FlowStatus.SEASONAL_EXPECTED)
    verdict = evaluate_guardrails(
        GuardrailInputs(
            segment=segment, flow_observations=(), now=utc_now()
        )
    )
    assert verdict.flow_pass is None
    policy_ids = {str(d.policy_id) for d in verdict.decisions}
    assert "mining-rights" in policy_ids
    assert verdict.actionability is Actionability.BLOCKED
