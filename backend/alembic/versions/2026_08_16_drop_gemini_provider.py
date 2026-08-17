"""drop_gemini_provider

Clear the retired `gemini` provider override so the Settings page and pipeline fall
back to the `.env` provider instead of a value the app no longer supports.

Revision ID: b41e7c02d9a3
Revises: 7d9c8f5e2a11
Create Date: 2026-08-16 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b41e7c02d9a3"
down_revision: Union[str, Sequence[str], None] = "7d9c8f5e2a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Null out retired provider overrides (and their Gemini-only base URL/model)."""
    op.execute(
        sa.text(
            "UPDATE app_settings "
            "SET llm_provider = NULL, llm_base_url = NULL, llm_model = NULL, "
            "    llm_api_key = NULL "
            "WHERE lower(llm_provider) IN ('gemini', 'google')"
        )
    )


def downgrade() -> None:
    """No-op: the removed values cannot be recovered."""
