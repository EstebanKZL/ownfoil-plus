"""A file kept on purpose: an older update that is never deleted as old

Revision ID: c9d0e1f2a3b6
Revises: b8c9d0e1f2a5

A plain ALTER TABLE ADD COLUMN - never Alembic's batch mode here: on SQLite that
rebuilds `files` (copy, drop, rename), and with the foreign keys on, dropping the old
table cascades into `app_files` and every file loses its link to its game.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b6'
down_revision = 'b8c9d0e1f2a5'
branch_labels = None
depends_on = None


def upgrade():
    columns = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('files')]
    if 'keep' not in columns:
        op.add_column('files', sa.Column('keep', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('files', 'keep')
