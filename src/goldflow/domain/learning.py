"""Calibration engine (PRD §10.1, §21.2): learn family weights from field labels.

Pure and deterministic. Consumes (family-subscore vector, label) pairs from
validated targets and fits a logistic model by fixed-iteration gradient
descent — no randomness, no external deps. Below the label threshold it emits
a report only; a fitted candidate never activates itself (PRD §15: no model
mutates the live score path without explicit review).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from goldflow.domain.results import Err, Ok, Result, ValidationError
from goldflow.domain.scoring import FeatureFamily

MIN_LABELS_FOR_FIT = 20
MIN_LABELS_PER_CLASS = 5
GRADIENT_ITERATIONS = 400
LEARNING_RATE = 0.5
L2_PENALTY = 0.02

CORE_FAMILIES: tuple[FeatureFamily, ...] = (
    FeatureFamily.SOURCE_SYSTEM,
    FeatureFamily.TRANSPORT,
    FeatureFamily.TRAP,
)


@dataclass(frozen=True, slots=True)
class LabeledExample:
    """Family subscores in [0,1] for one target plus its field outcome."""

    subscores: tuple[float, float, float]  # SOURCE_SYSTEM, TRANSPORT, TRAP
    positive: bool


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    n_labels: int
    n_positive: int
    n_negative: int
    enrichment: float | None  # mean positive score / mean overall score
    family_correlations: tuple[tuple[str, float], ...]
    fit_performed: bool
    candidate_weights: tuple[tuple[str, float], ...] | None
    holdout_accuracy: float | None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _point_biserial(feature: list[float], labels: list[bool]) -> float:
    """Correlation of one family subscore with the binary outcome."""
    if len(set(labels)) < 2:
        return 0.0
    pos = [f for f, y in zip(feature, labels, strict=True) if y]
    neg = [f for f, y in zip(feature, labels, strict=True) if not y]
    mean_all = _mean(feature)
    std = math.sqrt(_mean([(f - mean_all) ** 2 for f in feature]))
    if std == 0:
        return 0.0
    p = len(pos) / len(feature)
    return (_mean(pos) - _mean(neg)) * math.sqrt(p * (1 - p)) / std


def _sigmoid(z: float) -> float:
    if z < -35:
        return 0.0
    if z > 35:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _fit_logistic(
    rows: list[tuple[float, float, float]], labels: list[bool]
) -> tuple[float, float, float, float]:
    """Deterministic fixed-iteration gradient descent; returns (bias, w1, w2, w3)."""
    bias, weights = 0.0, [0.0, 0.0, 0.0]
    n = len(rows)
    for _ in range(GRADIENT_ITERATIONS):
        grad_b, grad_w = 0.0, [0.0, 0.0, 0.0]
        for row, y in zip(rows, labels, strict=True):
            pred = _sigmoid(bias + sum(w * x for w, x in zip(weights, row, strict=True)))
            error = pred - (1.0 if y else 0.0)
            grad_b += error
            for i in range(3):
                grad_w[i] += error * row[i]
        bias -= LEARNING_RATE * grad_b / n
        for i in range(3):
            weights[i] -= LEARNING_RATE * (grad_w[i] / n + L2_PENALTY * weights[i])
    return bias, weights[0], weights[1], weights[2]


def _weights_from_coefficients(coefficients: tuple[float, float, float]) -> dict[str, float]:
    """Map logistic coefficients to normalized family weights summing to 1.

    Negative coefficients clamp to a small floor: a family is never allowed to
    reward absence of its own signal (guards against label noise flipping signs).
    """
    floored = [max(0.05, c) for c in coefficients]
    total = sum(floored)
    return {
        family.value: round(value / total, 4)
        for family, value in zip(CORE_FAMILIES, floored, strict=True)
    }


def calibrate(
    examples: tuple[LabeledExample, ...],
    scores: tuple[tuple[float, bool], ...] = (),
) -> Result[CalibrationReport, ValidationError]:
    """Produce a calibration report; fit candidate weights when data suffices.

    ``scores``: (published score, positive) pairs for the enrichment metric
    (§2.3: top targets should enrich vs. baseline).
    """
    if not examples:
        return Err(ValidationError(code="NO_LABELS", message="no validated targets yet"))

    labels = [e.positive for e in examples]
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos

    enrichment: float | None = None
    if scores:
        overall = _mean([s for s, _ in scores])
        positive_scores = [s for s, y in scores if y]
        if positive_scores and overall > 0:
            enrichment = round(_mean(positive_scores) / overall, 4)

    columns = [[e.subscores[i] for e in examples] for i in range(3)]
    correlations = tuple(
        (family.value, round(_point_biserial(columns[i], labels), 4))
        for i, family in enumerate(CORE_FAMILIES)
    )

    can_fit = (
        len(examples) >= MIN_LABELS_FOR_FIT
        and n_pos >= MIN_LABELS_PER_CLASS
        and n_neg >= MIN_LABELS_PER_CLASS
    )
    candidate: tuple[tuple[str, float], ...] | None = None
    holdout_accuracy: float | None = None
    if can_fit:
        # Deterministic split: every 5th example held out (ordering is the
        # caller's stable DB ordering).
        train = [(e.subscores, e.positive) for i, e in enumerate(examples) if i % 5 != 0]
        holdout = [(e.subscores, e.positive) for i, e in enumerate(examples) if i % 5 == 0]
        bias, w1, w2, w3 = _fit_logistic([r for r, _ in train], [y for _, y in train])
        weight_map = _weights_from_coefficients((w1, w2, w3))
        candidate = tuple(sorted(weight_map.items()))
        if holdout:
            correct = sum(
                1
                for row, y in holdout
                if (
                    _sigmoid(bias + w1 * row[0] + w2 * row[1] + w3 * row[2]) >= 0.5
                )
                == y
            )
            holdout_accuracy = round(correct / len(holdout), 4)

    return Ok(
        CalibrationReport(
            n_labels=len(examples),
            n_positive=n_pos,
            n_negative=n_neg,
            enrichment=enrichment,
            family_correlations=correlations,
            fit_performed=can_fit,
            candidate_weights=candidate,
            holdout_accuracy=holdout_accuracy,
        )
    )
