"""Finite, durable retry policy for transient task failures."""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = depends_on = None


def upgrade():
    op.add_column("card", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("card", sa.Column("retry_backoff_s", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("card", sa.Column("retry_after", sa.Integer()))
    op.add_column("card", sa.Column("retry_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_card_retry_after", "card", ["retry_after"])
    op.add_column("run", sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    op.drop_column("run", "attempt")
    op.drop_index("ix_card_retry_after", table_name="card")
    with op.batch_alter_table("card") as batch:
        for name in ("retry_attempts", "retry_after", "retry_backoff_s", "max_attempts"):
            batch.drop_column(name)
