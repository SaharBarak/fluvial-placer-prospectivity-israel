"""Field-validation loop: assay ground truth → validation transitions (§14.1)."""

from __future__ import annotations

from uuid import uuid4

from goldflow.application.services.research import (
    AU_VALIDATION_PPB,
    _assay_validation_state,
)
from goldflow.domain.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceQuality,
    Measurement,
    SourceRef,
)
from goldflow.domain.targets import TargetState
from goldflow.domain.values import AuthorityClass, EvidenceId, Probability, SourceId


def _assay(value: float, below_detection: bool = False) -> Evidence:
    return Evidence(
        id=EvidenceId(uuid4()),
        kind=EvidenceKind.ASSAY_RESULT,
        location=None,
        observed_value=Measurement(
            analyte="Au", value=value, unit="ppb", below_detection=below_detection
        ),
        claim=None,
        confidence=Probability(0.95),
        quality=EvidenceQuality.HIGH,
        valid_time=None,
        source_ref=SourceRef(
            source_id=SourceId(uuid4()),
            authority=AuthorityClass.FIELD_GROUND_TRUTH,
            reference="sample/x",
            retrieved_at_iso="2026-08-15T00:00:00+00:00",
        ),
    )


def test_no_assays_no_validation() -> None:
    assert _assay_validation_state(()) is None


def test_anomalous_assay_validates_positive() -> None:
    state = _assay_validation_state((_assay(AU_VALIDATION_PPB + 1),))
    assert state is TargetState.VALIDATED_POSITIVE


def test_single_below_detection_is_not_falsification() -> None:
    assert _assay_validation_state((_assay(0.0, below_detection=True),)) is None


def test_repeated_below_detection_validates_negative() -> None:
    state = _assay_validation_state(
        (_assay(0.0, below_detection=True), _assay(0.0, below_detection=True))
    )
    assert state is TargetState.VALIDATED_NEGATIVE


def test_low_but_detected_assay_stays_unvalidated() -> None:
    assert _assay_validation_state((_assay(5.0),)) is None
