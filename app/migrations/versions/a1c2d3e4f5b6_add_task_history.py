"""Add task_history table

Revision ID: a1c2d3e4f5b6
Revises: c9d0e1f2a3b4

A completed task (and its whole subtree, if it has one) is deleted the moment it
finishes - see _try_complete_parent and execute_task in worker.py - so there was
never any lasting record that a scan, verify pass, or titledb update ran at all,
only whatever the file's own current state happens to say. This adds a small,
bounded log of completed top-level operations (see TaskHistory's own docstring),
not a full per-task audit trail.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c2d3e4f5b6'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'task_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_name', sa.String(), nullable=False),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_history_completed_at', 'task_history', ['completed_at'])


def downgrade():
    op.drop_index('ix_task_history_completed_at', table_name='task_history')
    op.drop_table('task_history')
