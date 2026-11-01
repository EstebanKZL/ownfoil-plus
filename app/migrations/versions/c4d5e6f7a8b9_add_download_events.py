"""Add download_events table

Revision ID: c4d5e6f7a8b9
Revises: b1c2d3e4f5a6

Files.download_count only says how often a file was taken, never by whom or when.
This adds a per-download log (see DownloadEvent's docstring) behind the Downloads
section of the Stats page.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'download_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('files.id', ondelete='SET NULL'), nullable=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('title_id', sa.String(), nullable=True),
        sa.Column('app_type', sa.String(), nullable=True),
        sa.Column('app_version', sa.String(), nullable=True),
        sa.Column('size', sa.BigInteger(), nullable=True),
        sa.Column('user', sa.String(), nullable=True),
        sa.Column('client', sa.String(), nullable=False),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('downloaded_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_download_events_downloaded_at', 'download_events', ['downloaded_at'])
    op.create_index('ix_download_events_title_id', 'download_events', ['title_id'])


def downgrade():
    op.drop_index('ix_download_events_title_id', table_name='download_events')
    op.drop_index('ix_download_events_downloaded_at', table_name='download_events')
    op.drop_table('download_events')
