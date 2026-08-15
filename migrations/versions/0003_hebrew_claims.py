"""Localize legacy evidence claims and source names to Hebrew.

Hebrew is the product language. Agent claim templates were localized earlier,
but pre-localization rows still surface in dossiers (they merge back in via
near-segment evidence). This data migration rewrites the templated English
claims to the exact current Hebrew templates, preserving every parameter
(formation name, percentages, confidences, distances). Formation names inside
geology claims stay as stored; the Hebrew display names arrive via
scripts/backfill_hebrew.py + the next research pass.

Rewritten rows get a fresh non-content fingerprint ('i18n1-…'): the stored
content hash no longer matches the claim, and re-deriving it here would risk
colliding with agent rows inserted since localization. Dedupe of future
identical proposals is handled by the (kind, source_reference) merge key.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (match pattern, replacement) — anchored so only legacy English rows rewrite.
_CLAIM_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (
        r"^Upstream lithology ('.*') covers (\d+)% of the drainage zone "
        r"\(favorability ([0-9.]+)\)$",
        r"ליתולוגיה במעלה האגן: \1 מכסה \2% מאזור הניקוז (התאמה \3)",
    ),
    (
        r"^Nearest mapped fault at (\d+) m from segment$",
        r"העתק ממופה קרוב במרחק \1 מ' מהמקטע",
    ),
    (
        r"^Segment '(.*)' classified (\S+) \(confidence ([0-9.]+)\) "
        r"from official spring-discharge/hydrometric evidence$",
        r"המקטע '\1' סווג \2 (ביטחון \3) על סמך נתוני ספיקת מעיינות "
        r"ותחנות הידרומטריות רשמיים",
    ),
    (
        r"^Field assay: (\S+) = (\S+) (\S+) \(lab: (.*)\)$",
        r"בדיקת מעבדה משטח: \1 = \2 \3 (מעבדה: \4)",
    ),
    (
        r"^Field assay: (\S+) = (\S+) (\S+)$",
        r"בדיקת מעבדה משטח: \1 = \2 \3",
    ),
    (
        r"^Sentinel-2 L2A coverage: (\d+) scenes in (\d+) d over pilot basin; "
        r"median cloud (\d+)%$",
        r"כיסוי Sentinel-2 L2A: \1 סצנות ב-\2 ימים באגן הפיילוט; "
        r"עננות חציונית \3%",
    ),
    (
        r"^Sentinel-2 L2A coverage: (\d+) scenes in (\d+) d over pilot basin$",
        r"כיסוי Sentinel-2 L2A: \1 סצנות ב-\2 ימים באגן הפיילוט",
    ),
)

_SOURCE_NAME_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (
        r"^OpenStreetMap waterways \(Overpass\)$",
        r"ערוצי נחלים — OpenStreetMap (Overpass)",
    ),
    (
        r"^Israel Water Authority — springs, discharge, hydrometric stations$",
        r"רשות המים — מעיינות, ספיקות ותחנות הידרומטריות",
    ),
    (
        r"^GSI 1:200,000 geological map \(2014\)$",
        r"המפה הגיאולוגית של ישראל 1:200,000 — המכון הגיאולוגי (2014)",
    ),
    (r"^Field assay (.*)$", r"בדיקת שטח — \1"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for pattern, replacement in _CLAIM_TRANSLATIONS:
        bind.execute(
            sa.text(
                "UPDATE core.evidence SET "
                "claim = regexp_replace(claim, :pat, :rep), "
                "fingerprint = 'i18n1-' || md5(id::text || claim) "
                "WHERE claim ~ :pat"
            ),
            {"pat": pattern, "rep": replacement},
        )
    for pattern, replacement in _SOURCE_NAME_TRANSLATIONS:
        bind.execute(
            sa.text(
                "UPDATE raw.source_document SET "
                "name = regexp_replace(name, :pat, :rep) "
                "WHERE name ~ :pat"
            ),
            {"pat": pattern, "rep": replacement},
        )


def downgrade() -> None:
    msg = "forward-only migrations (PRD §23.5)"
    raise NotImplementedError(msg)
