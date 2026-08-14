"""Next-measurement planning: Expected Information Gain heuristic (PRD §10.3).

EIGScore = ExpectedUncertaintyReduction * DecisionImpact / NormalizedCost.
The system ranks actions, not only sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from goldflow.domain.targets import Actionability
from goldflow.domain.values import TargetId


class MeasurementKind(StrEnum):
    SEDIMENT_ASSAY = "SEDIMENT_ASSAY"
    HEAVY_MINERAL_CONCENTRATE = "HEAVY_MINERAL_CONCENTRATE"
    FIELD_FLOW_OBSERVATION = "FIELD_FLOW_OBSERVATION"
    HIGH_RES_IMAGERY = "HIGH_RES_IMAGERY"
    LITERATURE_DEEP_DIVE = "LITERATURE_DEEP_DIVE"
    WATER_QUALITY_CHECK = "WATER_QUALITY_CHECK"


@dataclass(frozen=True, slots=True)
class MeasurementProposal:
    target_id: TargetId
    kind: MeasurementKind
    expected_uncertainty_reduction: float
    decision_impact: float
    normalized_cost: float
    actionability: Actionability
    rationale: str

    @property
    def eig_score(self) -> float:
        if self.normalized_cost <= 0:
            return 0.0
        return round(
            self.expected_uncertainty_reduction * self.decision_impact / self.normalized_cost, 4
        )


def choose_next_measurement(
    target_id: TargetId,
    uncertainty: float,
    score_value: float,
    actionability: Actionability,
    has_geochemistry: bool,
    has_current_flow: bool,
) -> MeasurementProposal:
    """Deterministic proposal selection.

    Missing flow evidence dominates (it gates everything). Otherwise a first
    assay is the highest-value measurement for a promising, un-sampled target;
    weak targets get cheap desk research first.
    """
    if not has_current_flow:
        return MeasurementProposal(
            target_id=target_id,
            kind=MeasurementKind.FIELD_FLOW_OBSERVATION,
            expected_uncertainty_reduction=min(1.0, uncertainty + 0.2),
            decision_impact=0.9,
            normalized_cost=0.2,
            actionability=actionability,
            rationale="flow status gates field eligibility; verifying flow unlocks the pipeline",
        )
    if not has_geochemistry and score_value >= 40.0:
        return MeasurementProposal(
            target_id=target_id,
            kind=MeasurementKind.SEDIMENT_ASSAY,
            expected_uncertainty_reduction=min(1.0, uncertainty),
            decision_impact=1.0,
            normalized_cost=0.5,
            actionability=actionability,
            rationale="no direct geochemistry yet; a first assay maximally reduces uncertainty",
        )
    if score_value < 40.0:
        return MeasurementProposal(
            target_id=target_id,
            kind=MeasurementKind.LITERATURE_DEEP_DIVE,
            expected_uncertainty_reduction=uncertainty * 0.4,
            decision_impact=0.5,
            normalized_cost=0.1,
            actionability=actionability,
            rationale="weak signal; cheap desk research before any field spend",
        )
    return MeasurementProposal(
        target_id=target_id,
        kind=MeasurementKind.HEAVY_MINERAL_CONCENTRATE,
        expected_uncertainty_reduction=uncertainty * 0.6,
        decision_impact=0.8,
        normalized_cost=0.6,
        actionability=actionability,
        rationale="geochemistry exists; concentrate sampling refines trap understanding",
    )
