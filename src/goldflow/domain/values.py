"""Shared domain value objects: units, identifiers, geometry wrappers.

All units are explicit. Canonical metric geometry lives in EPSG:2039
(Israel Transverse Mercator); API boundaries convert to EPSG:4326.
Distance math in degrees is unrepresentable by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import NewType, Self
from uuid import UUID

from goldflow.domain.results import Err, Ok, Result, ValidationError

RunId = NewType("RunId", UUID)
TargetId = NewType("TargetId", UUID)
EvidenceId = NewType("EvidenceId", UUID)
SourceId = NewType("SourceId", UUID)
WaterwayId = NewType("WaterwayId", UUID)
WaterwaySegmentId = NewType("WaterwaySegmentId", UUID)
CatchmentId = NewType("CatchmentId", UUID)
HypothesisId = NewType("HypothesisId", UUID)
TraceId = NewType("TraceId", UUID)
PolicyId = NewType("PolicyId", str)

EPSG_ITM = 2039
EPSG_WGS84 = 4326
EPSG_WEB_MERCATOR = 3857


@dataclass(frozen=True, slots=True)
class Meters:
    value: float

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("distance cannot be negative")


@dataclass(frozen=True, slots=True)
class Ppb:
    """Parts per billion; canonical unit for Au assay values."""

    value: float


@dataclass(frozen=True, slots=True)
class Ppm:
    value: float

    def to_ppb(self) -> Ppb:
        return Ppb(self.value * 1000.0)


@dataclass(frozen=True, slots=True)
class Probability:
    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"probability out of [0,1]: {self.value}")

    @classmethod
    def clamped(cls, raw: float) -> Probability:
        return cls(min(1.0, max(0.0, raw)))


@dataclass(frozen=True, slots=True)
class Score:
    """Public prospect score, 0-100. Not a calibrated probability (PRD §10.1)."""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 100.0:
            raise ValueError(f"score out of [0,100]: {self.value}")


@dataclass(frozen=True, slots=True)
class Point2039:
    """Point in EPSG:2039 (meters)."""

    x: float
    y: float

    def distance_to(self, other: Point2039) -> Meters:
        return Meters(((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5)


@dataclass(frozen=True, slots=True)
class Wgs84Point:
    lon: float
    lat: float

    @classmethod
    def create(cls, lon: float, lat: float) -> Result[Self, ValidationError]:
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return Err(ValidationError(code="INVALID_COORD", message=f"({lon},{lat})"))
        return Ok(cls(lon, lat))


@dataclass(frozen=True, slots=True)
class BBox2039:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("degenerate bbox")


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("naive datetime in TimeRange")
        if self.start > self.end:
            raise ValueError("start after end")

    def contains(self, at: datetime) -> bool:
        return self.start <= at <= self.end


class AuthorityClass(StrEnum):
    """Prior weight class of a source (PRD §6.1)."""

    AUTHORITATIVE = "AUTHORITATIVE"
    PEER_REVIEWED = "PEER_REVIEWED"
    OFFICIAL_AGGREGATION = "OFFICIAL_AGGREGATION"
    SECONDARY = "SECONDARY"
    FIELD_GROUND_TRUTH = "FIELD_GROUND_TRUTH"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)
