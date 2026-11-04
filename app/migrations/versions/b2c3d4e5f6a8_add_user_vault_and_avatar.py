"""Add each user's vault password and profile picture

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7

The save vault (vault.py) gives each user their own space and their own password for
JKSV, set in My account, instead of one shared login in Settings. The profile picture
(My account) is a gallery avatar's id or an uploaded image's file name.

Plain ADD COLUMN, no batch: a batch rebuild drops and recreates `user`, and with foreign
keys on that would cascade into the rows pointing at it.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('vault_password', sa.String(200), nullable=True))
    op.add_column('user', sa.Column('avatar', sa.String(64), nullable=True))


def downgrade():
    op.drop_column('user', 'avatar')           # SQLite 3.35+ drops a column in place
    op.drop_column('user', 'vault_password')
