"""Add the curated tone catalog and its PostgreSQL enum.

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TONE_VALUES = (
    "practical",
    "professional",
    "technical",
    "conversational",
    "friendly",
    "persuasive",
    "informative",
    "storytelling",
    "academic",
    "thought-provoking",
)

TONES = (
    ("practical", "Practical", "Clear, useful guidance readers can put into action."),
    ("professional", "Professional", "Polished, confident writing for a business audience."),
    ("technical", "Technical", "Precise explanations that are comfortable with detail."),
    ("conversational", "Conversational", "Natural, approachable writing that feels like a discussion."),
    ("friendly", "Friendly", "Warm and encouraging writing with an easygoing voice."),
    ("persuasive", "Persuasive", "Benefit-led writing that builds a clear case for an idea."),
    ("informative", "Informative", "Balanced, fact-focused writing that prioritizes clarity."),
    ("storytelling", "Storytelling", "Narrative writing that uses examples and a strong through-line."),
    ("academic", "Academic", "Formal, structured writing suited to scholarly topics."),
    ("thought-provoking", "Thought-provoking", "Reflective writing that invites readers to reconsider a topic."),
)


def upgrade() -> None:
    bind = op.get_bind()
    tone_enum = postgresql.ENUM(*TONE_VALUES, name="blog_tone_value", create_type=False)
    tone_enum.create(bind, checkfirst=True)

    op.create_table(
        "tone_catalog",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("value", tone_enum, nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sort_order"),
        sa.UniqueConstraint("value"),
    )

    tone_table = sa.table(
        "tone_catalog",
        sa.column("value", tone_enum),
        sa.column("label", sa.String(length=80)),
        sa.column("description", sa.String(length=255)),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        tone_table,
        [
            {
                "value": value,
                "label": label,
                "description": description,
                "sort_order": order,
            }
            for order, (value, label, description) in enumerate(TONES, start=1)
        ],
    )


def downgrade() -> None:
    op.drop_table("tone_catalog")
    postgresql.ENUM(name="blog_tone_value").drop(op.get_bind(), checkfirst=True)
