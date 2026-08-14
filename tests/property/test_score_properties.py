"""Hypothesis property tests (PRD §18.3)."""

from __future__ import annotations

from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from goldflow.domain.geology import fault_proximity_factor, lithology_favorability
from goldflow.domain.results import Ok
from goldflow.domain.scoring import (
    FeatureFamily,
    FeatureValue,
    TargetFeatures,
    score_target,
)
from goldflow.domain.values import EvidenceId, Meters, TargetId


@st.composite
def feature_values(draw: st.DrawFn) -> FeatureValue:
    family = draw(st.sampled_from(list(FeatureFamily)))
    name = draw(
        st.text(alphabet="abcdefghijklmnop_", min_size=3, max_size=20)
    )
    normalized = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    return FeatureValue(
        name=name,
        family=family,
        normalized=normalized,
        evidence_ids=(EvidenceId(uuid4()),),
    )


@st.composite
def feature_vectors(draw: st.DrawFn) -> TargetFeatures:
    features = draw(
        st.lists(feature_values(), min_size=1, max_size=12, unique_by=lambda f: f.name)
    )
    return TargetFeatures(TargetId(uuid4()), tuple(features), ())


@given(feature_vectors())
@settings(max_examples=200)
def test_score_always_bounded(features: TargetFeatures) -> None:
    result = score_target(features)
    assert isinstance(result, Ok)
    assert 0.0 <= result.value.score.value <= 100.0
    assert 0.0 <= result.value.uncertainty <= 1.0


@given(feature_vectors(), st.randoms())
@settings(max_examples=100)
def test_score_permutation_invariant(features: TargetFeatures, rng) -> None:
    shuffled = list(features.features)
    rng.shuffle(shuffled)
    original = score_target(features)
    permuted = score_target(
        TargetFeatures(features.target_id, tuple(shuffled), features.evidence)
    )
    assert isinstance(original, Ok) and isinstance(permuted, Ok)
    assert original.value.score == permuted.value.score


@given(st.floats(min_value=0.0, max_value=100_000.0, allow_nan=False))
def test_fault_proximity_monotone_decreasing(distance: float) -> None:
    nearer = fault_proximity_factor(Meters(distance))
    farther = fault_proximity_factor(Meters(distance + 500.0))
    assert 0.0 <= farther <= nearer <= 1.0


@given(st.text(max_size=200))
def test_lithology_favorability_total(description: str) -> None:
    value = lithology_favorability(description)
    assert 0.0 <= value <= 1.0
