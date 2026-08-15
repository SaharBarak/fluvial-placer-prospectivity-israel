"""Calibration engine (domain/learning.py): pure, deterministic, human-gated."""

from __future__ import annotations

from goldflow.domain.learning import (
    MIN_LABELS_FOR_FIT,
    CalibrationReport,
    LabeledExample,
    calibrate,
)
from goldflow.domain.results import Err, Ok


def _example(source: float, transport: float, trap: float, *, positive: bool) -> LabeledExample:
    return LabeledExample(subscores=(source, transport, trap), positive=positive)


def _separable_dataset() -> tuple[LabeledExample, ...]:
    """SOURCE_SYSTEM cleanly separates classes; other families are flat noise."""
    positives = tuple(
        _example(0.8 + 0.01 * i, 0.5, 0.5, positive=True) for i in range(12)
    )
    negatives = tuple(
        _example(0.1 + 0.01 * i, 0.5, 0.5, positive=False) for i in range(12)
    )
    # Interleave so the every-5th holdout split contains both classes.
    mixed: list[LabeledExample] = []
    for p, n in zip(positives, negatives, strict=True):
        mixed.extend((p, n))
    return tuple(mixed)


def test_no_labels_is_error() -> None:
    result = calibrate(())
    assert isinstance(result, Err)
    assert result.error.code == "NO_LABELS"


def test_below_threshold_reports_without_fit() -> None:
    examples = (
        _example(0.9, 0.5, 0.4, positive=True),
        _example(0.2, 0.5, 0.4, positive=False),
    )
    result = calibrate(examples)
    assert isinstance(result, Ok)
    report = result.value
    assert report.n_labels == 2
    assert report.fit_performed is False
    assert report.candidate_weights is None
    assert report.holdout_accuracy is None


def test_separable_data_fits_and_favors_discriminating_family() -> None:
    examples = _separable_dataset()
    assert len(examples) >= MIN_LABELS_FOR_FIT
    result = calibrate(examples)
    assert isinstance(result, Ok)
    report = result.value
    assert report.fit_performed is True
    assert report.candidate_weights is not None
    weights = dict(report.candidate_weights)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # The family that separates the classes must dominate the fitted weights.
    assert weights["SOURCE_SYSTEM"] == max(weights.values())
    assert report.holdout_accuracy is not None
    assert report.holdout_accuracy >= 0.9


def test_calibrate_is_deterministic() -> None:
    examples = _separable_dataset()
    first = calibrate(examples)
    second = calibrate(examples)
    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert first.value == second.value


def test_correlations_signal_direction() -> None:
    examples = _separable_dataset()
    result = calibrate(examples)
    assert isinstance(result, Ok)
    correlations = dict(result.value.family_correlations)
    assert correlations["SOURCE_SYSTEM"] > 0.8
    assert abs(correlations["TRANSPORT"]) < 0.1


def test_enrichment_from_published_scores() -> None:
    examples = (
        _example(0.9, 0.5, 0.4, positive=True),
        _example(0.2, 0.5, 0.4, positive=False),
    )
    scores = ((80.0, True), (40.0, False))
    result = calibrate(examples, scores)
    assert isinstance(result, Ok)
    # mean positive 80 / mean overall 60
    assert result.value.enrichment == 1.3333


def test_negative_coefficient_never_rewards_absence_of_signal() -> None:
    """A family anti-correlated with success floors at 0.05 share, never negative."""
    positives = tuple(
        _example(0.8, 0.1 + 0.01 * i, 0.5, positive=True) for i in range(12)
    )
    negatives = tuple(
        _example(0.1, 0.9 - 0.01 * i, 0.5, positive=False) for i in range(12)
    )
    mixed: list[LabeledExample] = []
    for p, n in zip(positives, negatives, strict=True):
        mixed.extend((p, n))
    result = calibrate(tuple(mixed))
    assert isinstance(result, Ok)
    report: CalibrationReport = result.value
    assert report.candidate_weights is not None
    weights = dict(report.candidate_weights)
    assert all(w > 0 for w in weights.values())  # 0.05 floor pre-normalization
