"""Add membership plans to accounts and a monthly usage ledger.

Accounts get a plan (FREE by default) with a start and an expiry. `membership_usage`
records what an account used in a calendar month (KST): one row per notice whose
qualification was checked, and one row per Copilot question asked inside a notice.
Limits are enforced by app/membership.py only where MEMBERSHIP_LIMITS_ENABLED is on.

Existing accounts become FREE. The system administrator is exempt by role, not by plan.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "030_membership_plans"
down_revision = "029_notice_participation_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("membership_plan", sa.Text(), nullable=False, server_default="FREE"))
    op.add_column("app_users", sa.Column("membership_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_users", sa.Column("membership_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_app_users_membership_plan", "app_users", "membership_plan IN ('FREE', 'BASIC', 'UNLIMITED')",
    )
    op.create_table(
        "membership_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('NOTICE_CHECK', 'COPILOT_QUESTION')", name="ck_membership_usage_kind"),
    )
    op.create_index("ix_membership_usage_user_period", "membership_usage", ["user_id", "period", "kind"])
    op.create_index(
        "uq_membership_usage_notice_check", "membership_usage", ["user_id", "period", "subject_id"],
        unique=True, postgresql_where=sa.text("kind = 'NOTICE_CHECK'"),
    )


def downgrade() -> None:
    op.drop_index("uq_membership_usage_notice_check", table_name="membership_usage")
    op.drop_index("ix_membership_usage_user_period", table_name="membership_usage")
    op.drop_table("membership_usage")
    op.drop_constraint("ck_app_users_membership_plan", "app_users", type_="check")
    op.drop_column("app_users", "membership_expires_at")
    op.drop_column("app_users", "membership_started_at")
    op.drop_column("app_users", "membership_plan")
