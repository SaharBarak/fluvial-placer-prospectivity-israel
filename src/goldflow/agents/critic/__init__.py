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
                    f"ליתולוגיה קרבונטית/דלת-התאמה מכסה "
                    f"{carbonate_fraction:.0%} מהאזור במעלה; אין מערכת מקור "
                    "קרובה סבירה לזהב סחף"
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
                    "התרעת איכות מים סמוך למקטע: קלט מתכות אנתרופוגני יכול "
                    "להסביר אותות גיאוכימיים ללא מערכת נושאת זהב"
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
                    f"סטטוס זרימה {segment.flow_status.value}: חיפוש תת-מימי "
                    "מחייב זרימה עדכנית מאומתת"
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
                    f"רק {len(committed_evidence)} פריטי ראיות; הדירוג נשען על "
                    "נגזרות גיאומטריות יותר מאשר על נתונים מדודים"
                ),
                evidence_ids=(),
            )
        )

    objections.append(
        Objection(
            kind=ObjectionKind.SENSOR_LIMITATION,
            severity=ObjectionSeverity.LOW,
            statement=(
                "אין מדידת Au ישירה למקטע זה; כל האותות מלוויין/מפות הם "
                "פרוקסי עקיף בלבד (AC-14)"
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
            f"הועלו {len(objections)} התנגדויות; ההסבר החלופי החזק ביותר: "
            + (objections[0].statement[:80] if objections else "אין"),
            (),
        ),
    )
