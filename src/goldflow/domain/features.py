"""Evidence bundle → TargetFeatures: the pure evaluation pipeline (PRD §23.2).

Spatial joins are executed by infrastructure (PostGIS); their *results* arrive
here as value objects. This module stays pure and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldflow.domain.evidence import Evidence, EvidenceKind
from goldflow.domain.geology import (
    UpstreamLithology,
    catchment_source_potential,
    fault_proximity_factor,
)
from goldflow.domain.hydrology import FlowObservation, WaterwaySegment
from goldflow.domain.results import Err, Ok, Result, ValidationError
from goldflow.domain.scoring import FeatureFamily, FeatureValue, TargetFeatures
from goldflow.domain.values import EvidenceId, Meters, TargetId


@dataclass(frozen=True, slots=True)
class SpatialContext:
    """Deterministic geometric facts computed by the spatial engine, with lineage."""

    upstream_lithologies: tuple[UpstreamLithology, ...]
    lithology_evidence_ids: tuple[EvidenceId, ...]
    nearest_fault_distance: Meters | None
    fault_evidence_ids: tuple[EvidenceId, ...]
    upstream_length_m: float
    segment_slope_pct: float | None
    confluence_count: int
    sinuosity: float | None


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    target_id: TargetId
    segment: WaterwaySegment
    spatial: SpatialContext
    evidence: tuple[Evidence, ...]
    flow_observations: tuple[FlowObservation, ...]


def _slope_trap_factor(slope_pct: float) -> float:
    """Placer traps favor gradient breaks: moderate slopes score highest.

    <0.5% too flat (fines only), 1-4% ideal energy drop, >8% transport-through.
    """
    if slope_pct < 0.1:
        return 0.2
    if slope_pct < 1.0:
        return 0.5
    if slope_pct <= 4.0:
        return 1.0
    if slope_pct <= 8.0:
        return 0.6
    return 0.3


def _sinuosity_factor(sinuosity: float) -> float:
    """Meandering channels (>1.2) develop point-bar traps."""
    if sinuosity <= 1.05:
        return 0.3
    if sinuosity <= 1.2:
        return 0.6
    if sinuosity <= 1.6:
        return 1.0
    return 0.8


def build_target_features(
    bundle: EvidenceBundle,
) -> Result[TargetFeatures, ValidationError]:
    """Derive the frozen feature vector. Pure; order/duplicate invariant."""
    features: list[FeatureValue] = []
    spatial = bundle.spatial

    # --- SOURCE_SYSTEM ---
    if spatial.upstream_lithologies:
        features.append(
            FeatureValue(
                name="upstream_lithology_favorability",
                family=FeatureFamily.SOURCE_SYSTEM,
                normalized=round(catchment_source_potential(spatial.upstream_lithologies), 4),
                evidence_ids=spatial.lithology_evidence_ids,
                deterministic_derivation="area-weighted lithology favorability v1",
            )
        )
    if spatial.nearest_fault_distance is not None:
        features.append(
            FeatureValue(
                name="structural_context",
                family=FeatureFamily.SOURCE_SYSTEM,
                normalized=fault_proximity_factor(spatial.nearest_fault_distance),
                evidence_ids=spatial.fault_evidence_ids,
                deterministic_derivation="fault distance decay(2km) v1",
            )
        )
    mineral_evidence = tuple(
        sorted(
            (e for e in bundle.evidence if e.kind == EvidenceKind.MINERAL_OCCURRENCE),
            key=lambda e: str(e.id),
        )
    )
    if mineral_evidence:
        features.append(
            FeatureValue(
                name="known_mineral_occurrence_upstream",
                family=FeatureFamily.SOURCE_SYSTEM,
                normalized=min(1.0, 0.5 + 0.25 * len(mineral_evidence)),
                evidence_ids=tuple(e.id for e in mineral_evidence),
            )
        )
    geochem = tuple(
        sorted(
            (
                e
                for e in bundle.evidence
                if e.kind in (EvidenceKind.GEOCHEMICAL_SAMPLE, EvidenceKind.ASSAY_RESULT)
                and e.observed_value is not None
                and not e.observed_value.below_detection
            ),
            key=lambda e: str(e.id),
        )
    )
    if geochem:
        strongest = max(
            (e.observed_value.value for e in geochem if e.observed_value is not None),
            default=0.0,
        )
        # Au ppb: 5 ppb background → 1000 ppb strongly anomalous (log-ish steps)
        magnitude = min(1.0, max(0.0, (strongest / 200.0) ** 0.5))
        features.append(
            FeatureValue(
                name="upstream_geochemical_signal",
                family=FeatureFamily.SOURCE_SYSTEM,
                normalized=round(magnitude, 4),
                evidence_ids=tuple(e.id for e in geochem),
            )
        )

    # --- TRANSPORT ---
    if spatial.upstream_length_m > 0:
        features.append(
            FeatureValue(
                name="upstream_connectivity",
                family=FeatureFamily.TRANSPORT,
                normalized=round(min(1.0, spatial.upstream_length_m / 20_000.0), 4),
                evidence_ids=(),
                deterministic_derivation="upstream drainage length / 20km cap v1",
            )
        )

    # --- TRAP ---
    if spatial.segment_slope_pct is not None:
        features.append(
            FeatureValue(
                name="gradient_trap_context",
                family=FeatureFamily.TRAP,
                normalized=_slope_trap_factor(spatial.segment_slope_pct),
                evidence_ids=(),
                deterministic_derivation="slope band trap heuristic v1",
            )
        )
    if spatial.confluence_count > 0:
        features.append(
            FeatureValue(
                name="confluence_density",
                family=FeatureFamily.TRAP,
                normalized=min(1.0, spatial.confluence_count / 4.0),
                evidence_ids=(),
                deterministic_derivation="confluences within segment buffer v1",
            )
        )
    if spatial.sinuosity is not None:
        features.append(
            FeatureValue(
                name="channel_sinuosity",
                family=FeatureFamily.TRAP,
                normalized=_sinuosity_factor(spatial.sinuosity),
                evidence_ids=(),
                deterministic_derivation="segment sinuosity band v1",
            )
        )

    # --- CONTAMINATION ---
    contamination = tuple(
        sorted(
            (
                e
                for e in bundle.evidence
                if e.kind in (EvidenceKind.CONTAMINATION_SOURCE, EvidenceKind.WATER_QUALITY)
                and e.contamination_risk is not None
            ),
            key=lambda e: str(e.id),
        )
    )
    for item in contamination:
        risk = item.contamination_risk
        if risk is None:
            continue
        features.append(
            FeatureValue(
                name=f"contamination_{str(item.id)[:8]}",
                family=FeatureFamily.CONTAMINATION,
                normalized=risk.value,
                evidence_ids=(item.id,),
            )
        )

    if not features:
        return Err(
            ValidationError(
                code="EMPTY_FEATURE_VECTOR",
                message=f"no derivable features for target {bundle.target_id}",
            )
        )
    return Ok(
        TargetFeatures(
            target_id=bundle.target_id,
            features=tuple(sorted(features, key=lambda f: f.name)),
            evidence=bundle.evidence,
        )
    )
