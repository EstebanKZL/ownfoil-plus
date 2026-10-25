"""Add media table for local artwork

Revision ID: d7e8f9a0b1c2
Revises: a1c2d3e4f5b6

One row per artwork slot a title fills (icon, banner, each screenshot by position) -
not per file. The file itself, every rendition of it, lives on disk under the derived
data directory (see constants.MEDIA_DIR); this row just says which stored filename
fills which slot, and where it came from, so Local artworks (Settings) can serve it
locally instead of hotlinking Nintendo's CDN.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e8f9a0b1c2'
down_revision = 'a1c2d3e4f5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'media',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_url', sa.String(), nullable=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('downloaded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('title_id', 'kind', 'position', name='uq_media_slot'),
    )
    op.create_index('ix_media_title_id', 'media', ['title_id'])


def downgrade():
    op.drop_index('ix_media_title_id', table_name='media')
    op.drop_table('media')
