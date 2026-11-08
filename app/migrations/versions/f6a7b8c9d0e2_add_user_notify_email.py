"""Add a per-user choice to get the server's notifications by email, and the language
the user last used the web in (those emails are written in it)

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d1
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e2'
down_revision = 'e5f6a7b8c9d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('notify_email', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('user', sa.Column('language', sa.String(8), nullable=True))


def downgrade():
    with op.batch_alter_table('user') as batch:
        batch.drop_column('notify_email')
        batch.drop_column('language')
