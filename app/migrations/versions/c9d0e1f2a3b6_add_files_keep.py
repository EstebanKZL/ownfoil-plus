"""A file kept on purpose: an older update that is never deleted as old

Revision ID: c9d0e1f2a3b6
Revises: b8c9d0e1f2a5
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b6'
down_revision = 'b8c9d0e1f2a5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('files') as batch:
        batch.add_column(sa.Column('keep', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('files') as batch:
        batch.drop_column('keep')
