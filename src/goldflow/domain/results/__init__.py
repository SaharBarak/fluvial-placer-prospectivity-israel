"""Result monad and typed error taxonomy.

Domain and application boundaries never raise expected failures; they return
``Result[T, E]``. Exceptions from libraries are caught at adapter boundaries
and converted to ``Err``. Programming errors still raise.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True


type Result[T, E] = Ok[T] | Err[E]


def bind[T, U, E](result: Result[T, E], fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
    match result:
        case Ok(value):
            return fn(value)
        case Err(error):
            return Err(error)


def map_ok[T, U, E](result: Result[T, E], fn: Callable[[T], U]) -> Result[U, E]:
    match result:
        case Ok(value):
            return Ok(fn(value))
        case Err(error):
            return Err(error)


def unwrap_or[T, E](result: Result[T, E], default: T) -> T:
    match result:
        case Ok(value):
            return value
        case Err():
            return default


def collect[T, E](results: Iterable[Result[T, E]]) -> Result[tuple[T, ...], E]:
    """All-or-first-error aggregation preserving order."""
    values: list[T] = []
    for result in results:
        match result:
            case Ok(value):
                values.append(value)
            case Err(error):
                return Err(error)
    return Ok(tuple(values))


def partition[T, E](results: Iterable[Result[T, E]]) -> tuple[tuple[T, ...], tuple[E, ...]]:
    """Split into successes and failures without short-circuiting."""
    values: list[T] = []
    errors: list[E] = []
    for result in results:
        match result:
            case Ok(value):
                values.append(value)
            case Err(error):
                errors.append(error)
    return tuple(values), tuple(errors)


# --- Error taxonomy (PRD §17.5) ---


@dataclass(frozen=True, slots=True)
class DomainError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationError(DomainError):
    field: str | None = None


@dataclass(frozen=True, slots=True)
class SpatialInvariantError(DomainError):
    geometry_hint: str | None = None


@dataclass(frozen=True, slots=True)
class FlowVerificationError(DomainError):
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceQualityError(DomainError):
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class GuardrailViolation(DomainError):
    policy_id: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceUnavailable(ApplicationError):
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class BudgetExceeded(ApplicationError):
    budget_kind: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowConflict(ApplicationError):
    run_id: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyFailed(ApplicationError):
    dependency: str | None = None


@dataclass(frozen=True, slots=True)
class InfrastructureError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DatabaseError(InfrastructureError):
    pass


@dataclass(frozen=True, slots=True)
class ArcGisError(InfrastructureError):
    service: str | None = None


@dataclass(frozen=True, slots=True)
class StacError(InfrastructureError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectStoreError(InfrastructureError):
    pass


@dataclass(frozen=True, slots=True)
class ModelProviderError(InfrastructureError):
    pass
