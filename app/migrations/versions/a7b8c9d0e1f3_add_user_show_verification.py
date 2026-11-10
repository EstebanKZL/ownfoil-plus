"""Add a per-user choice to show the verification marks (empty: as the server says)

Revision ID: a7b8c9d0e1f3
Revises: f6a7b8c9d0e2
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f3'
down_revision = 'f6a7b8c9d0e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('show_verification', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('user') as batch:
        batch.drop_column('show_verification')
