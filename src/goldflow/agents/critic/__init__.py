"""Critic/Falsifier agent (PRD §7): the strongest no-gold explanation.

Required before score finalization (AC-06). Produces objections that lower
nothing directly — the deterministic scorer consumes contamination features and
the dossier shows the critique.
"""

from __future__ import annotations

from goldflow.agents.rationale import cite
from goldflow.domain.agents import (
    AgentArtifact,
    Objection,
    ObjectionKind,
    ObjectionSeverity,
)
from goldflow.domain.evidence import Evidence, EvidenceKind
from goldflow.domain.geology import lithology_favorability
from goldflow.domain.hydrology import FIELD_ELIGIBLE_STATUSES, WaterwaySegment
from goldflow.infrastructure.db.spatial import SegmentSpatialFacts

AGENT_NAME = "critic"

CARBONATE_DOMINANCE_THRESHOLD = 0.65
MIN_EVIDENCE_FOR_CONFIDENCE = 3


def critique_target(
    segment: WaterwaySegment,
    facts: SegmentSpatialFacts,
    committed_evidence: tuple[Evidence, ...],
) -> AgentArtifact:
    objections: list[Objection] = []

    carbonate_fraction = sum(
        lith.area_fraction
        for lith in facts.upstream_lithologies
        if lithology_favorability(lith.description) <= 0.2
    )
    if carbonate_fraction >= CARBONATE_DOMINANCE_THRESHOLD:
        objections.append(
            Objection(
                kind=ObjectionKind.NON_GOLD_LITHOLOGY,
                severity=ObjectionSeverity.HIGH,
                statement=(
                    f"Carbonate/low-favorability lithology covers "
                    f"{carbonate_fraction:.0%} of the upstream zone; no plausible "
                    "proximal source system for placer gold"
                ),
                evidence_ids=tuple(
                    e.id for e in committed_evidence if e.kind == EvidenceKind.GEOLOGICAL_UNIT
                ),
            )
        )

    if facts.water_quality_alert_nearby:
        objections.append(
            Objection(
                kind=ObjectionKind.CONTAMINATION_ALTERNATIVE,
                severity=ObjectionSeverity.MEDIUM,
                statement=(
                    "Water-quality alert near segment: anthropogenic metal input can "
                    "explain geochemical signals without a gold-bearing system"
                ),
                evidence_ids=tuple(
                    e.id for e in committed_evidence if e.kind == EvidenceKind.WATER_QUALITY
                ),
            )
        )

    if segment.flow_status not in FIELD_ELIGIBLE_STATUSES:
        objections.append(
            Objection(
                kind=ObjectionKind.FLOW_UNVERIFIED,
                severity=ObjectionSeverity.HIGH,
                statement=(
                    f"Flow status {segment.flow_status.value}: underwater prospecting "
                    "scope requires verified current flow"
                ),
                evidence_ids=(),
            )
        )

    if len(committed_evidence) < MIN_EVIDENCE_FOR_CONFIDENCE:
        objections.append(
            Objection(
                kind=ObjectionKind.WEAK_EVIDENCE,
                severity=ObjectionSeverity.MEDIUM,
                statement=(
                    f"Only {len(committed_evidence)} evidence items; ranking rests on "
                    "geometric derivations more than measured data"
                ),
                evidence_ids=(),
            )
        )

    objections.append(
        Objection(
            kind=ObjectionKind.SENSOR_LIMITATION,
            severity=ObjectionSeverity.LOW,
            statement=(
                "No direct Au measurement exists for this segment; all satellite/"
                "map-derived signals are indirect proxies (AC-14)"
            ),
            evidence_ids=(),
        )
    )

    return AgentArtifact(
        agent_name=AGENT_NAME,
        claims=(),
        proposed_evidence=(),
        objections=tuple(objections),
        next_actions=(),
        rationale_summary=cite(
            f"Raised {len(objections)} objections; strongest alternative: "
            + (objections[0].statement[:80] if objections else "none"),
            (),
        ),
    )
