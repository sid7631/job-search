"""add_job_enrichment

Adds the columns the enrich stage and the "new since last run" digest need:
detail_text / detail_fetched_at (full posting text, kept out of `description` so the
nightly re-scrape cannot overwrite it) and first_seen_run_id.

Revision ID: c72a5f31b8e4
Revises: b41e7c02d9a3
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c72a5f31b8e4"
down_revision: Union[str, Sequence[str], None] = "b41e7c02d9a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("detail_text", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("detail_fetched_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("first_seen_run_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_jobs_first_seen_run_id", ["first_seen_run_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_first_seen_run_id")
        batch_op.drop_column("first_seen_run_id")
        batch_op.drop_column("detail_fetched_at")
        batch_op.drop_column("detail_text")
