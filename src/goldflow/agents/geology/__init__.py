"""Geology agent (PRD §7): source-rock context for a target segment.

Emits Evidence proposals grounded in GSI features that spatially intersect the
segment's upstream zone. Never sets scores (PRD §5.2).
"""

from __future__ import annotations

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
from goldflow.domain.geology import lithology_favorability
from goldflow.domain.values import (
    AuthorityClass,
    EvidenceId,
    Point2039,
    Probability,
    SourceId,
    utc_now,
)
from goldflow.infrastructure.db.spatial import SegmentSpatialFacts

AGENT_NAME = "geology"
FAVORABLE_THRESHOLD = 0.6


def analyze_geology(
    facts: SegmentSpatialFacts,
    gsi_source_id: SourceId,
    segment_midpoint: Point2039,
) -> AgentArtifact:
    """Deterministic policy: lithology mix + structural context into evidence."""
    proposed: list[Evidence] = []
    claims: list[Claim] = []

    for lith in facts.upstream_lithologies[:6]:
        favorability = lithology_favorability(lith.description)
        polarity = (
            EvidencePolarity.SUPPORTS
            if favorability >= FAVORABLE_THRESHOLD
            else EvidencePolarity.NEUTRAL
            if favorability >= 0.3
            else EvidencePolarity.REFUTES
        )
        evidence = Evidence(
            id=EvidenceId(uuid4()),
            kind=EvidenceKind.GEOLOGICAL_UNIT,
            location=segment_midpoint,
            observed_value=None,
            claim=(
                f"Upstream lithology '{lith.description}' covers "
                f"{lith.area_fraction:.0%} of the drainage zone "
                f"(favorability {favorability:.2f})"
            ),
            confidence=Probability(0.85),
            quality=EvidenceQuality.HIGH,
            valid_time=None,
            source_ref=SourceRef(
                source_id=gsi_source_id,
                authority=AuthorityClass.AUTHORITATIVE,
                reference=lith.unit_reference,
                retrieved_at_iso=utc_now().isoformat(),
            ),
        )
        proposed.append(evidence)
        claims.append(
            Claim(
                statement=evidence.claim or "",
                polarity=polarity,
                evidence_ids=(evidence.id,),
                confidence=0.85,
            )
        )

    if facts.nearest_fault_distance is not None:
        fault_evidence = Evidence(
            id=EvidenceId(uuid4()),
            kind=EvidenceKind.STRUCTURAL_FEATURE,
            location=segment_midpoint,
            observed_value=None,
            claim=(
                f"Nearest mapped fault at {facts.nearest_fault_distance.value:.0f} m "
                "from segment"
            ),
            confidence=Probability(0.8),
            quality=EvidenceQuality.HIGH,
            valid_time=None,
            source_ref=SourceRef(
                source_id=gsi_source_id,
                authority=AuthorityClass.AUTHORITATIVE,
                reference="gsi-faults-layer/0",
                retrieved_at_iso=utc_now().isoformat(),
            ),
        )
        proposed.append(fault_evidence)
        claims.append(
            Claim(
                statement=fault_evidence.claim or "",
                polarity=EvidencePolarity.SUPPORTS
                if facts.nearest_fault_distance.value < 2000
                else EvidencePolarity.NEUTRAL,
                evidence_ids=(fault_evidence.id,),
                confidence=0.8,
            )
        )

    return AgentArtifact(
        agent_name=AGENT_NAME,
        claims=tuple(claims),
        proposed_evidence=tuple(proposed),
        objections=(),
        next_actions=(),
        rationale_summary=cite(
            f"Mapped {len(facts.upstream_lithologies)} upstream lithology units and "
            f"fault context from GSI 1:200k layers",
            tuple(e.id for e in proposed),
        ),
    )
