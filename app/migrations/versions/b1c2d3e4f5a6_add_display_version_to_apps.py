"""Add display_version column to apps

Revision ID: b1c2d3e4f5a6
Revises: d7e8f9a0b1c2

Carries the human-readable version string a content's own Control NCA reports (e.g.
"1.2.0"), read at identification time from the file itself - distinct from
`app_version`, which is the raw Nintendo version counter (a multiple of 65536) and is
what /admin/files fell back to showing ("v0" for a first release) before this existed.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('apps', sa.Column('display_version', sa.String(), nullable=True))


def downgrade():
    op.drop_column('apps', 'display_version')
