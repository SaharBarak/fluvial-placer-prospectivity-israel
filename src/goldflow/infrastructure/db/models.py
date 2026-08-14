"""SQLAlchemy ORM rows (infrastructure only — PRD §11.4).

Domain entities never inherit DeclarativeBase; repositories map rows to
frozen domain objects. Canonical geometry SRID is EPSG:2039.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SRID_ITM = 2039


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


class SourceDocumentRow(Base):
    __tablename__ = "source_document"
    __table_args__ = {"schema": "raw"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_class: Mapped[str] = mapped_column(String(32), nullable=False)
    license: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_method: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class WaterwayRow(Base):
    __tablename__ = "waterway"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str | None] = mapped_column(String(255))
    name_he: Mapped[str | None] = mapped_column(String(255))


class WaterwaySegmentRow(Base):
    __tablename__ = "waterway_segment"
    __table_args__ = (
        Index("ix_waterway_segment_geom", "geom", postgresql_using="gist"),
        Index("ix_waterway_segment_flow_status", "flow_status"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    waterway_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.waterway.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(255))
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("LINESTRING", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    flow_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    flow_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    flow_valid_until: Mapped[datetime | None] = mapped_column()
    length_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    upstream_length_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slope_pct: Mapped[float | None] = mapped_column(Float)
    sinuosity: Mapped[float | None] = mapped_column(Float)
    confluence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw.source_document.id"))
    source_feature_ref: Mapped[str | None] = mapped_column(String(255))


class SpringRow(Base):
    __tablename__ = "spring"
    __table_args__ = (
        Index("ix_spring_geom", "geom", postgresql_using="gist"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str | None] = mapped_column(String(255))
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    discharge_lps: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime | None] = mapped_column()
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw.source_document.id"))
    source_feature_ref: Mapped[str | None] = mapped_column(String(255))


class GeologicalUnitRow(Base):
    __tablename__ = "geological_unit"
    __table_args__ = (
        Index("ix_geological_unit_geom", "geom", postgresql_using="gist"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    unit_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lithology: Mapped[str | None] = mapped_column(Text)
    age: Mapped[str | None] = mapped_column(String(255))
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw.source_document.id"))


class StructuralFeatureRow(Base):
    __tablename__ = "structural_feature"
    __table_args__ = (
        Index("ix_structural_feature_geom", "geom", postgresql_using="gist"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # FAULT/CONTACT/...
    name: Mapped[str | None] = mapped_column(String(255))
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("MULTILINESTRING", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw.source_document.id"))
    source_feature_ref: Mapped[str | None] = mapped_column(String(255))


class WaterQualityPointRow(Base):
    __tablename__ = "water_quality_point"
    __table_args__ = (
        Index("ix_water_quality_point_geom", "geom", postgresql_using="gist"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    station_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    observed_at: Mapped[datetime | None] = mapped_column()
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw.source_document.id"))


class EvidenceRow(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_geom", "geom", postgresql_using="gist"),
        Index("ix_evidence_kind", "kind"),
        Index("ix_evidence_fingerprint", "fingerprint", unique=True),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    geom: Mapped[WKBElement | None] = mapped_column(
        Geometry("POINT", srid=SRID_ITM, spatial_index=False)
    )
    analyte: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(24))
    detection_limit: Mapped[float | None] = mapped_column(Float)
    below_detection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    claim: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_start: Mapped[datetime | None] = mapped_column()
    valid_end: Mapped[datetime | None] = mapped_column()
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw.source_document.id"), nullable=False
    )
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)
    contamination_risk: Mapped[float | None] = mapped_column(Float)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ProspectTargetRow(Base):
    __tablename__ = "prospect_target"
    __table_args__ = (
        Index("ix_prospect_target_geom", "geom", postgresql_using="gist"),
        Index("ix_prospect_target_state", "state"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    waterway_segment_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.waterway_segment.id"), nullable=False
    )
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    actionability: Mapped[str] = mapped_column(
        String(32), nullable=False, default="OBSERVE_ONLY"
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class FieldSampleRow(Base):
    __tablename__ = "field_sample"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.prospect_target.id"), nullable=False
    )
    geom: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=SRID_ITM, spatial_index=False), nullable=False
    )
    medium: Mapped[str] = mapped_column(String(48), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(nullable=False)
    collector: Mapped[str | None] = mapped_column(String(255))
    permit_state: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    notes: Mapped[str | None] = mapped_column(Text)


class AssayResultRow(Base):
    __tablename__ = "assay_result"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    field_sample_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.field_sample.id"), nullable=False
    )
    analyte: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    lod: Mapped[float | None] = mapped_column(Float)
    loq: Mapped[float | None] = mapped_column(Float)
    lab: Mapped[str | None] = mapped_column(String(255))
    method: Mapped[str | None] = mapped_column(String(255))
    reported_at: Mapped[datetime] = mapped_column(nullable=False)


class ScoreSnapshotRow(Base):
    __tablename__ = "score_snapshot"
    __table_args__ = (
        Index("ix_score_snapshot_target", "target_id"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.prospect_target.id"), nullable=False
    )
    run_id: Mapped[UUID | None] = mapped_column()
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class MeasurementProposalRow(Base):
    __tablename__ = "measurement_proposal"
    __table_args__ = (
        Index("ix_measurement_proposal_target", "target_id"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.prospect_target.id"), nullable=False
    )
    run_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    eig_score: Mapped[float] = mapped_column(Float, nullable=False)
    expected_uncertainty_reduction: Mapped[float] = mapped_column(Float, nullable=False)
    decision_impact: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_cost: Mapped[float] = mapped_column(Float, nullable=False)
    actionability: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ResearchRunRow(Base):
    __tablename__ = "research_run"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    code_commit: Mapped[str | None] = mapped_column(String(64))
    config_hash: Mapped[str | None] = mapped_column(String(64))
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)


class DecisionTraceRow(Base):
    __tablename__ = "decision_trace"
    __table_args__ = (
        Index("ix_decision_trace_run", "run_id"),
        Index("ix_decision_trace_target", "target_id"),
        {"schema": "audit"},
    )

    trace_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(nullable=False)
    target_id: Mapped[UUID | None] = mapped_column()
    state_before: Mapped[str] = mapped_column(String(48), nullable=False)
    state_after: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    tool_calls: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    derived_features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    objections: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    scoring_model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rationale_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class GuardrailEventRow(Base):
    __tablename__ = "guardrail_event"
    __table_args__ = (
        Index("ix_guardrail_event_target", "target_id"),
        {"schema": "audit"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID | None] = mapped_column()
    target_id: Mapped[UUID] = mapped_column(nullable=False)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column()
    remediation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
