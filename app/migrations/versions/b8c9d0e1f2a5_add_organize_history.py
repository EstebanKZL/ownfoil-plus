"""Keep the moves of the last Organize runs, so one can be put back

Revision ID: b8c9d0e1f2a5
Revises: a7b8c9d0e1f3
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a5'
down_revision = 'a7b8c9d0e1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'organize_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(), nullable=False, unique=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('undone_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'organize_moves',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('organize_runs.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('file_id', sa.Integer(), nullable=True),
        sa.Column('old_path', sa.String(), nullable=False),
        sa.Column('new_path', sa.String(), nullable=False),
        sa.Column('moved_at', sa.DateTime(), nullable=False),
        sa.Column('undone', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_table('organize_moves')
    op.drop_table('organize_runs')
