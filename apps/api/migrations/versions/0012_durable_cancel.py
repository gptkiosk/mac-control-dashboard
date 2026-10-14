"""Durable run control: the runner's pid and a small JSON checkpoint per run.

`run.pid` lets restart recovery stop a runner a crashed service left alive. `run.checkpoint`
holds a committed operator cancel request and the quarantine record of a run's partial output,
in the same shape RCD uses. Both columns are nullable; existing rows are unchanged.
"""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = depends_on = None


def upgrade():
    op.add_column('run', sa.Column('pid', sa.Integer))
    op.add_column('run', sa.Column('checkpoint', sa.Text))


def downgrade():
    with op.batch_alter_table('run') as batch:
        for name in ('checkpoint', 'pid'):
            batch.drop_column(name)
