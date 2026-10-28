"""email provider choice (Amazon SES or Resend)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "application_settings",
        sa.Column("email_provider", sa.String(16), server_default=sa.text("'ses'"), nullable=False),
    )
    op.add_column("application_settings", sa.Column("resend_sender", sa.String(320), nullable=True))
    op.create_check_constraint(
        "ck_application_settings_email_provider", "application_settings", "email_provider in ('ses', 'resend')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_application_settings_email_provider", "application_settings", type_="check")
    op.drop_column("application_settings", "resend_sender")
    op.drop_column("application_settings", "email_provider")
