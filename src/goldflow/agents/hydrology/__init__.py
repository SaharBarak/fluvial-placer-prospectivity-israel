"""Hydrology/Flow agent (PRD §7): flow evidence and transport context.

Synthesizes FlowObservation domain objects from the segment's classified state
(which was derived from official spring discharge / hydrometric stations at
ingestion time) and emits flow evidence with lineage.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from goldflow.agents.rationale import cite
from goldflow.domain.agents import AgentArtifact, Claim
from goldflow.domain.evidence import (
    Evidence,
    EvidenceKind,
    EvidencePolarity,
    EvidenceQuality,
    SourceRef,
)
from goldflow.domain.hydrology import (
    FIELD_ELIGIBLE_STATUSES,
    FlowEvidenceKind,
    FlowObservation,
    WaterwaySegment,
)
from goldflow.domain.values import (
    AuthorityClass,
    EvidenceId,
    Point2039,
    SourceId,
    utc_now,
)
from goldflow.infrastructure.db.spatial import SegmentSpatialFacts

AGENT_NAME = "hydrology"


def flow_observations_for_segment(
    segment: WaterwaySegment, water_source_id: SourceId
) -> tuple[FlowObservation, ...]:
    """Reify the segment's ingested flow classification as domain observations."""
    if segment.flow_status not in FIELD_ELIGIBLE_STATUSES:
        return ()
    now = utc_now()
    valid_until = segment.flow_valid_until or (now - timedelta(seconds=1))
    return (
        FlowObservation(
            segment_id=segment.id,
            kind=FlowEvidenceKind.SPRING_DISCHARGE,
            status=segment.flow_status,
            confidence=segment.flow_confidence,
            observed_at=now - timedelta(days=1),
            valid_until=valid_until,
            source_id=water_source_id,
        ),
    )


def analyze_hydrology(
    segment: WaterwaySegment,
    facts: SegmentSpatialFacts,
    water_source_id: SourceId,
    segment_midpoint: Point2039,
) -> AgentArtifact:
    proposed: list[Evidence] = []
    claims: list[Claim] = []

    flow_claim = (
        f"Segment '{segment.name or segment.id}' classified {segment.flow_status.value} "
        f"(confidence {segment.flow_confidence.value:.2f}) from official spring-discharge/"
        "hydrometric evidence"
    )
    flow_evidence = Evidence(
        id=EvidenceId(uuid4()),
        kind=EvidenceKind.FLOW_OBSERVATION,
        location=segment_midpoint,
        observed_value=None,
        claim=flow_claim,
        confidence=segment.flow_confidence,
        quality=(
            EvidenceQuality.HIGH
            if segment.flow_status in FIELD_ELIGIBLE_STATUSES
            else EvidenceQuality.MEDIUM
        ),
        valid_time=None,
        source_ref=SourceRef(
            source_id=water_source_id,
            authority=AuthorityClass.AUTHORITATIVE,
            reference=f"segment-flow/{segment.id}",
            retrieved_at_iso=utc_now().isoformat(),
        ),
    )
    proposed.append(flow_evidence)
    claims.append(
        Claim(
            statement=flow_claim,
            polarity=(
                EvidencePolarity.SUPPORTS
                if segment.flow_status in FIELD_ELIGIBLE_STATUSES
                else EvidencePolarity.NEUTRAL
            ),
            evidence_ids=(flow_evidence.id,),
            confidence=segment.flow_confidence.value,
        )
    )

    transport_claim = (
        f"Upstream drainage length {facts.upstream_length_m / 1000:.1f} km with "
        f"{facts.confluence_count} nearby confluences"
    )
    claims.append(
        Claim(
            statement=transport_claim,
            polarity=(
                EvidencePolarity.SUPPORTS
                if facts.upstream_length_m > 3000
                else EvidencePolarity.NEUTRAL
            ),
            evidence_ids=(),
            confidence=0.7,
        )
    )

    return AgentArtifact(
        agent_name=AGENT_NAME,
        claims=tuple(claims),
        proposed_evidence=tuple(proposed),
        objections=(),
        next_actions=(),
        rationale_summary=cite(
            f"Flow status {segment.flow_status.value}; upstream connectivity "
            f"{facts.upstream_length_m / 1000:.1f} km",
            (flow_evidence.id,),
        ),
    )
