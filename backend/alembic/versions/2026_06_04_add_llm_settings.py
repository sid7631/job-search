"""add_llm_settings

Revision ID: 7d9c8f5e2a11
Revises: 0983fe5c5c08
Create Date: 2026-06-04 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7d9c8f5e2a11"
down_revision: Union[str, Sequence[str], None] = "0983fe5c5c08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_provider", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("llm_base_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("llm_api_key", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("llm_model", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("llm_model")
        batch_op.drop_column("llm_api_key")
        batch_op.drop_column("llm_base_url")
        batch_op.drop_column("llm_provider")
