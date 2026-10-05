"""triage_progress_exclude

Supports the triage-first Today page:
- `applications.dismiss_reason`: why a job was passed on ("wrong_stack", ...), which
  feeds the ranker's taste examples.
- `runs.progress_json`: the live stage of a running pipeline, plus any prompt that
  needs the user (e.g. approve the LinkedIn sign-in on your phone).
- `app_settings.exclude_keywords`: title terms that remove a job before ranking.

Revision ID: e5a1c9b3f7d2
Revises: d83f6a24c1b7
Create Date: 2026-10-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5a1c9b3f7d2"
down_revision: Union[str, Sequence[str], None] = "d83f6a24c1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dismiss_reason", sa.String(length=50), nullable=True))
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("progress_json", sa.JSON(), nullable=True, server_default="{}")
        )
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("exclude_keywords", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("exclude_keywords")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("progress_json")
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_column("dismiss_reason")
