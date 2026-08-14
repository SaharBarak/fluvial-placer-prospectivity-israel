"""Deterministic scoring engine (PRD §10).

Score = f(source_system, transport, trap, evidence_quality, contamination).
Not a calibrated probability: public value is ProspectScore 0-100 plus a
separate Uncertainty 0-1. Every non-zero component carries evidence lineage.
The computation is order-invariant and duplicate-invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from goldflow.domain.evidence import Evidence, dedupe_evidence, evidence_weight
from goldflow.domain.results import Err, EvidenceQualityError, Ok, Result
from goldflow.domain.values import EvidenceId, Score, TargetId

SCORING_MODEL_VERSION = "prospect-v1"


class FeatureFamily(StrEnum):
    SOURCE_SYSTEM = "SOURCE_SYSTEM"  # upstream geology/geochemistry/structure
    TRANSPORT = "TRANSPORT"  # catchment connectivity, erosion
    TRAP = "TRAP"  # channel morphology, slope, energy
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    CONTAMINATION = "CONTAMINATION"


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """A named, normalized feature with evidence lineage.

    ``normalized`` must be in [0,1]. A feature with no evidence ids and no
    deterministic derivation carries zero numeric weight (PRD §15.1).
    """

    name: str
    family: FeatureFamily
    normalized: float
    evidence_ids: tuple[EvidenceId, ...]
    deterministic_derivation: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.normalized <= 1.0:
            raise ValueError(f"feature {self.name} normalized out of [0,1]")

    @property
    def grounded(self) -> bool:
        return bool(self.evidence_ids) or self.deterministic_derivation is not None


@dataclass(frozen=True, slots=True)
class TargetFeatures:
    target_id: TargetId
    features: tuple[FeatureValue, ...]
    evidence: tuple[Evidence, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    feature: str
    family: FeatureFamily
    raw_normalized: float
    weight: float
    contribution: float
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True, slots=True)
class ScoreSnapshot:
    target_id: TargetId
    model_version: str
    score: Score
    uncertainty: float
    components: tuple[ScoreComponent, ...]

    def top_drivers(self, n: int = 3) -> tuple[ScoreComponent, ...]:
        positive = [c for c in self.components if c.contribution > 0]
        return tuple(sorted(positive, key=lambda c: (-c.contribution, c.feature))[:n])


# Weights are versioned config, not prompts (PRD §5.2).
FAMILY_WEIGHTS: dict[FeatureFamily, float] = {
    FeatureFamily.SOURCE_SYSTEM: 0.40,
    FeatureFamily.TRANSPORT: 0.25,
    FeatureFamily.TRAP: 0.35,
}


def _family_subscore(
    features: tuple[FeatureValue, ...], family: FeatureFamily
) -> tuple[float, tuple[FeatureValue, ...]]:
    """Mean of grounded features in a family; sorted for order invariance."""
    members = tuple(
        sorted(
            (f for f in features if f.family == family and f.grounded),
            key=lambda f: f.name,
        )
    )
    if not members:
        return 0.0, ()
    return sum(f.normalized for f in members) / len(members), members


def _evidence_quality_factor(evidence: tuple[Evidence, ...]) -> float:
    """Mean deterministic weight of deduplicated evidence; 0.5 floor when absent
    so quality modulates rather than annihilates a geometrically-derived score."""
    unique = dedupe_evidence(evidence)
    if not unique:
        return 0.5
    weights = sorted(evidence_weight(e) for e in unique)
    return 0.5 + 0.5 * (sum(weights) / len(weights))


def _contamination_discount(features: tuple[FeatureValue, ...]) -> float:
    """1.0 = clean; grounded contamination features reduce multiplicatively."""
    risks = sorted(
        f.normalized
        for f in features
        if f.family == FeatureFamily.CONTAMINATION and f.grounded
    )
    discount = 1.0
    for risk in risks:
        discount *= 1.0 - 0.6 * risk
    return discount


def _uncertainty(features: tuple[FeatureValue, ...], evidence: tuple[Evidence, ...]) -> float:
    """More grounded families and heavier evidence => lower uncertainty."""
    core_families = (FeatureFamily.SOURCE_SYSTEM, FeatureFamily.TRANSPORT, FeatureFamily.TRAP)
    covered = sum(
        1 for fam in core_families if any(f.family == fam and f.grounded for f in features)
    )
    coverage = covered / len(core_families)
    unique = dedupe_evidence(evidence)
    evidence_mass = min(1.0, len(unique) / 8.0)
    return round(1.0 - (0.6 * coverage + 0.4 * evidence_mass), 4)


def score_target(features: TargetFeatures) -> Result[ScoreSnapshot, EvidenceQualityError]:
    """Deterministic score composition. Pure; invariant to feature/evidence order."""
    ungrounded_nonzero = [
        f for f in features.features if not f.grounded and f.normalized > 0.0
    ]
    if ungrounded_nonzero:
        return Err(
            EvidenceQualityError(
                code="UNGROUNDED_FEATURE",
                message=f"features without lineage carry no weight: "
                f"{[f.name for f in ungrounded_nonzero]}",
            )
        )

    components: list[ScoreComponent] = []
    weighted_sum = 0.0
    for family, weight in FAMILY_WEIGHTS.items():
        subscore, members = _family_subscore(features.features, family)
        weighted_sum += weight * subscore
        components.extend(
            ScoreComponent(
                feature=member.name,
                family=family,
                raw_normalized=member.normalized,
                weight=weight / max(1, len(members)),
                contribution=round(100.0 * weight * member.normalized / max(1, len(members)), 4),
                evidence_ids=tuple(sorted(member.evidence_ids, key=str)),
            )
            for member in members
        )

    quality = _evidence_quality_factor(features.evidence)
    discount = _contamination_discount(features.features)
    raw = 100.0 * weighted_sum * quality * discount
    final = Score(round(min(100.0, max(0.0, raw)), 2))

    components.append(
        ScoreComponent(
            feature="evidence_quality_factor",
            family=FeatureFamily.EVIDENCE_QUALITY,
            raw_normalized=round(quality, 4),
            weight=1.0,
            contribution=0.0,
            evidence_ids=tuple(
                sorted((e.id for e in dedupe_evidence(features.evidence)), key=str)
            ),
        )
    )
    components.append(
        ScoreComponent(
            feature="contamination_discount",
            family=FeatureFamily.CONTAMINATION,
            raw_normalized=round(discount, 4),
            weight=1.0,
            contribution=0.0,
            evidence_ids=tuple(
                sorted(
                    (
                        eid
                        for f in features.features
                        if f.family == FeatureFamily.CONTAMINATION
                        for eid in f.evidence_ids
                    ),
                    key=str,
                )
            ),
        )
    )

    return Ok(
        ScoreSnapshot(
            target_id=features.target_id,
            model_version=SCORING_MODEL_VERSION,
            score=final,
            uncertainty=_uncertainty(features.features, features.evidence),
            components=tuple(sorted(components, key=lambda c: (c.family.value, c.feature))),
        )
    )
