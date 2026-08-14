"""Evidence domain (PRD §9): normalized claims/measurements with provenance.

Every non-zero score component must trace to at least one Evidence id or a
deterministic geometric feature with lineage. Uncited claims carry zero
numeric weight.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from goldflow.domain.values import (
    AuthorityClass,
    EvidenceId,
    Point2039,
    Probability,
    SourceId,
    TimeRange,
)


class EvidenceKind(StrEnum):
    GEOLOGICAL_UNIT = "GEOLOGICAL_UNIT"
    STRUCTURAL_FEATURE = "STRUCTURAL_FEATURE"
    MINERAL_OCCURRENCE = "MINERAL_OCCURRENCE"
    GEOCHEMICAL_SAMPLE = "GEOCHEMICAL_SAMPLE"
    FLOW_OBSERVATION = "FLOW_OBSERVATION"
    SPRING_DISCHARGE = "SPRING_DISCHARGE"
    WATER_QUALITY = "WATER_QUALITY"
    REMOTE_SENSING = "REMOTE_SENSING"
    MORPHOLOGY = "MORPHOLOGY"
    HISTORICAL_REPORT = "HISTORICAL_REPORT"
    ASSAY_RESULT = "ASSAY_RESULT"
    CONTAMINATION_SOURCE = "CONTAMINATION_SOURCE"


class EvidenceQuality(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRELIABLE = "UNRELIABLE"


class EvidencePolarity(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class Measurement:
    analyte: str
    value: float
    unit: str
    detection_limit: float | None = None
    below_detection: bool = False


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: SourceId
    authority: AuthorityClass
    reference: str  # dataset feature id, report page/span, STAC item id
    retrieved_at_iso: str


@dataclass(frozen=True, slots=True)
class Evidence:
    id: EvidenceId
    kind: EvidenceKind
    location: Point2039 | None
    observed_value: Measurement | None
    claim: str | None
    confidence: Probability
    quality: EvidenceQuality
    valid_time: TimeRange | None
    source_ref: SourceRef
    contamination_risk: Probability | None = None

    def fingerprint(self) -> str:
        """Content fingerprint for the deduplication invariant (§18.2).

        Identical duplicate evidence must not double a score.
        """
        parts = (
            self.kind.value,
            f"{self.location.x:.1f},{self.location.y:.1f}" if self.location else "-",
            (
                f"{self.observed_value.analyte}:{self.observed_value.value}:{self.observed_value.unit}"
                if self.observed_value
                else "-"
            ),
            self.claim or "-",
            str(self.source_ref.source_id),
            self.source_ref.reference,
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


def dedupe_evidence(items: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    """Order-preserving dedup by content fingerprint."""
    seen: set[str] = set()
    unique: list[Evidence] = []
    for item in items:
        fp = item.fingerprint()
        if fp not in seen:
            seen.add(fp)
            unique.append(item)
    return tuple(unique)


AUTHORITY_PRIOR: dict[AuthorityClass, float] = {
    AuthorityClass.FIELD_GROUND_TRUTH: 1.0,
    AuthorityClass.AUTHORITATIVE: 0.9,
    AuthorityClass.PEER_REVIEWED: 0.85,
    AuthorityClass.OFFICIAL_AGGREGATION: 0.75,
    AuthorityClass.SECONDARY: 0.5,
}

QUALITY_FACTOR: dict[EvidenceQuality, float] = {
    EvidenceQuality.HIGH: 1.0,
    EvidenceQuality.MEDIUM: 0.75,
    EvidenceQuality.LOW: 0.45,
    EvidenceQuality.UNRELIABLE: 0.0,
}


def evidence_weight(item: Evidence) -> float:
    """Deterministic weight in [0,1] combining authority prior, quality, confidence."""
    return (
        AUTHORITY_PRIOR[item.source_ref.authority]
        * QUALITY_FACTOR[item.quality]
        * item.confidence.value
    )
