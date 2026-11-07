"""Add collaborator access: users who see the admin pages and change nothing

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d1'
down_revision = 'd4e5f6a7b8c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('collaborator_access', sa.Boolean(), nullable=False,
                                    server_default='0'))


def downgrade():
    with op.batch_alter_table('user') as batch:
        batch.drop_column('collaborator_access')
