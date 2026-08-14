"""Scoring invariants (PRD §18.2-§18.3)."""

from __future__ import annotations

import random
from uuid import uuid4

from goldflow.domain.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceQuality,
    SourceRef,
)
from goldflow.domain.results import Err, Ok
from goldflow.domain.scoring import (
    FeatureFamily,
    FeatureValue,
    TargetFeatures,
    score_target,
)
from goldflow.domain.values import (
    AuthorityClass,
    EvidenceId,
    Probability,
    SourceId,
    TargetId,
)


def _evidence(claim: str = "test claim") -> Evidence:
    return Evidence(
        id=EvidenceId(uuid4()),
        kind=EvidenceKind.GEOLOGICAL_UNIT,
        location=None,
        observed_value=None,
        claim=claim,
        confidence=Probability(0.9),
        quality=EvidenceQuality.HIGH,
        valid_time=None,
        source_ref=SourceRef(
            source_id=SourceId(uuid4()),
            authority=AuthorityClass.AUTHORITATIVE,
            reference="ref-1",
            retrieved_at_iso="2026-08-15T00:00:00+00:00",
        ),
    )


def _grounded(name: str, family: FeatureFamily, value: float) -> FeatureValue:
    return FeatureValue(name, family, value, (EvidenceId(uuid4()),))


def test_score_is_bounded() -> None:
    features = TargetFeatures(
        TargetId(uuid4()),
        (
            _grounded("a", FeatureFamily.SOURCE_SYSTEM, 1.0),
            _grounded("b", FeatureFamily.TRANSPORT, 1.0),
            _grounded("c", FeatureFamily.TRAP, 1.0),
        ),
        (_evidence(),),
    )
    result = score_target(features)
    assert isinstance(result, Ok)
    assert 0.0 <= result.value.score.value <= 100.0


def test_feature_order_does_not_change_score() -> None:
    base = [
        _grounded("alpha", FeatureFamily.SOURCE_SYSTEM, 0.7),
        _grounded("beta", FeatureFamily.SOURCE_SYSTEM, 0.3),
        _grounded("gamma", FeatureFamily.TRAP, 0.9),
        _grounded("delta", FeatureFamily.TRANSPORT, 0.5),
    ]
    evidence = (_evidence("one"), _evidence("two"))
    target_id = TargetId(uuid4())
    shuffled = base[:]
    random.Random(42).shuffle(shuffled)  # noqa: S311 — deterministic test shuffle
    first = score_target(TargetFeatures(target_id, tuple(base), evidence))
    second = score_target(TargetFeatures(target_id, tuple(shuffled), evidence))
    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert first.value.score == second.value.score
    assert first.value.uncertainty == second.value.uncertainty


def test_duplicate_evidence_does_not_double_score() -> None:
    """Identical duplicate evidence must not change the outcome (§18.2)."""
    item = _evidence("same claim")
    duplicate = Evidence(
        id=EvidenceId(uuid4()),  # different id, same content
        kind=item.kind,
        location=item.location,
        observed_value=item.observed_value,
        claim=item.claim,
        confidence=item.confidence,
        quality=item.quality,
        valid_time=item.valid_time,
        source_ref=item.source_ref,
    )
    features = (_grounded("a", FeatureFamily.SOURCE_SYSTEM, 0.8),)
    target_id = TargetId(uuid4())
    single = score_target(TargetFeatures(target_id, features, (item,)))
    doubled = score_target(TargetFeatures(target_id, features, (item, duplicate)))
    assert isinstance(single, Ok) and isinstance(doubled, Ok)
    assert single.value.score == doubled.value.score


def test_ungrounded_nonzero_feature_rejected() -> None:
    """An uncited claim cannot increase score (PRD §15.1)."""
    features = TargetFeatures(
        TargetId(uuid4()),
        (FeatureValue("phantom", FeatureFamily.SOURCE_SYSTEM, 0.9, ()),),
        (),
    )
    result = score_target(features)
    assert isinstance(result, Err)
    assert result.error.code == "UNGROUNDED_FEATURE"


def test_contamination_reduces_score() -> None:
    clean = TargetFeatures(
        TargetId(uuid4()),
        (_grounded("a", FeatureFamily.SOURCE_SYSTEM, 0.8),),
        (),
    )
    dirty = TargetFeatures(
        TargetId(uuid4()),
        (
            _grounded("a", FeatureFamily.SOURCE_SYSTEM, 0.8),
            _grounded("contamination_x", FeatureFamily.CONTAMINATION, 0.9),
        ),
        (),
    )
    clean_result = score_target(clean)
    dirty_result = score_target(dirty)
    assert isinstance(clean_result, Ok) and isinstance(dirty_result, Ok)
    assert dirty_result.value.score.value < clean_result.value.score.value


def test_uncertainty_floor_without_direct_geochemistry() -> None:
    features = TargetFeatures(
        TargetId(uuid4()),
        (
            _grounded("a", FeatureFamily.SOURCE_SYSTEM, 1.0),
            _grounded("b", FeatureFamily.TRANSPORT, 1.0),
            _grounded("c", FeatureFamily.TRAP, 1.0),
        ),
        tuple(_evidence(f"claim {i}") for i in range(10)),
    )
    result = score_target(features)
    assert isinstance(result, Ok)
    assert result.value.uncertainty >= 0.30
