"""add_run_source_errors

Separates isolated per-source collector failures from the fatal error that ends a
run, so one dead scraper no longer makes an otherwise successful run look failed.

Revision ID: d83f6a24c1b7
Revises: c72a5f31b8e4
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d83f6a24c1b7"
down_revision: Union[str, Sequence[str], None] = "c72a5f31b8e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source_errors_json", sa.JSON(), nullable=True, server_default="{}")
        )
    # Past runs that only ever recorded a collector failure were marked SUCCESS with
    # a scary error_text; move those messages across so the UI reads them correctly.
    op.execute(
        sa.text(
            "UPDATE runs SET source_errors_json = json_object('collector', error_text), "
            "error_text = NULL "
            "WHERE status = 'SUCCESS' AND error_text IS NOT NULL AND error_text != ''"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("source_errors_json")
