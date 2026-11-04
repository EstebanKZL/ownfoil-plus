"""Add emails, verification and Google sign-in to users

Revision ID: a1b2c3d4e5f7
Revises: f9a0b1c2d3e4

For accounts people make themselves (accounts.py): a verified email, one waiting for
its link, the Google account linked, and `pending` for a registration waiting for its
email. Existing users get no email, are verified for the purpose of signing in (pending
false) and keep signing in as before.

Plain ADD COLUMN and unique indexes, no batch: a batch rebuild drops and recreates
`user`, and with foreign keys on that would cascade into the rows pointing at it.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f7'
down_revision = 'f9a0b1c2d3e4'
branch_labels = None
depends_on = None


COLUMNS = ('email', 'email_verified', 'pending_email', 'google_id', 'pending')


def upgrade():
    op.add_column('user', sa.Column('email', sa.String(254), nullable=True))
    op.add_column('user', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('user', sa.Column('pending_email', sa.String(254), nullable=True))
    op.add_column('user', sa.Column('google_id', sa.String(64), nullable=True))
    op.add_column('user', sa.Column('pending', sa.Boolean(), nullable=False, server_default='0'))
    op.create_index('ix_user_email', 'user', ['email'], unique=True)
    op.create_index('ix_user_google_id', 'user', ['google_id'], unique=True)


def downgrade():
    op.drop_index('ix_user_google_id', table_name='user')
    op.drop_index('ix_user_email', table_name='user')
    for name in reversed(COLUMNS):
        op.drop_column('user', name)     # SQLite 3.35+ drops a column in place
