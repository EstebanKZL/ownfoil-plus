"""Add the firmware each base game and update needs, read from its own file

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8

titledb's cnmts.json leaves requiredSystemVersion empty for many older updates, so the
game page could not say which firmware they need. The file itself carries it in its
CNMT: identification now stores it here, and the game page falls back to it.

Plain ADD COLUMN, no batch, like the previous migrations.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b9'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('apps', sa.Column('required_system_version', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('apps', 'required_system_version')     # SQLite 3.35+ drops in place
