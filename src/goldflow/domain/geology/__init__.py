"""Geology domain: lithology favorability and structural context.

Favorability encodes placer-source plausibility of mapped lithology, not Au
presence. Versioned config, not prompt content (PRD §5.2). Keyword matching
runs against GSI unit descriptions (English + Hebrew fragments).
"""

from __future__ import annotations

from dataclasses import dataclass

from goldflow.domain.values import Meters

# (keyword, favorability 0..1) — first match wins; ordered most→least specific.
_LITHOLOGY_FAVORABILITY: tuple[tuple[str, float], ...] = (
    ("granite", 0.85),
    ("גרניט", 0.85),
    ("gneiss", 0.8),
    ("schist", 0.8),
    ("צפחה", 0.8),
    ("metamorph", 0.78),
    ("מטמורפ", 0.78),
    ("plutonic", 0.82),
    ("פלוטוני", 0.82),
    ("magmatic", 0.75),
    ("מגמטי", 0.75),
    ("rhyolite", 0.7),
    ("porphyr", 0.72),
    ("diorite", 0.7),
    ("quartz", 0.65),
    ("קוורץ", 0.65),
    ("volcan", 0.5),
    ("basalt", 0.35),
    ("בזלת", 0.35),
    ("tuff", 0.4),
    ("conglomerate", 0.55),
    ("קונגלומרט", 0.55),
    ("sandstone", 0.45),
    ("אבן חול", 0.45),
    ("alluvium", 0.5),
    ("סחף", 0.5),
    ("gravel", 0.5),
    ("marl", 0.15),
    ("חוואר", 0.15),
    ("chalk", 0.1),
    ("קרטון", 0.1),
    ("limestone", 0.12),
    ("גיר", 0.12),
    ("dolomite", 0.12),
    ("דולומיט", 0.12),
    ("clay", 0.15),
    ("חרסית", 0.15),
)

DEFAULT_FAVORABILITY = 0.25


def lithology_favorability(description: str) -> float:
    """Deterministic keyword-based favorability in [0,1]."""
    lowered = description.lower()
    for keyword, value in _LITHOLOGY_FAVORABILITY:
        if keyword in lowered:
            return value
    return DEFAULT_FAVORABILITY


@dataclass(frozen=True, slots=True)
class UpstreamLithology:
    """A lithology unit intersecting the target's upstream catchment."""

    unit_reference: str
    description: str
    area_fraction: float  # fraction of upstream catchment area

    def weighted_favorability(self) -> float:
        return lithology_favorability(self.description) * self.area_fraction


def catchment_source_potential(units: tuple[UpstreamLithology, ...]) -> float:
    """Area-weighted favorability of the upstream lithology mix, [0,1]."""
    if not units:
        return 0.0
    return min(1.0, sum(u.weighted_favorability() for u in units))


def fault_proximity_factor(distance: Meters, decay_m: float = 2000.0) -> float:
    """Exponential-like decay: 1.0 at the fault, ~0.37 at decay distance."""
    if decay_m <= 0:
        return 0.0
    ratio = distance.value / decay_m
    return round(2.0 ** (-ratio), 4)
