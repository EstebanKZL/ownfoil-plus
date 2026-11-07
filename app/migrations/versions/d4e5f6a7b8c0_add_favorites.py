"""Add favourites: the games each user marks with the star

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9

One row per user and title id, like the wishlist. The Library filters by the signed-in
user's own favourites; a user deleted takes them along.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c0'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'favorite',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title_id', sa.String(16), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'title_id', name='uq_favorite_user_title'),
    )
    op.create_index('ix_favorite_user_id', 'favorite', ['user_id'])


def downgrade():
    op.drop_index('ix_favorite_user_id', table_name='favorite')
    op.drop_table('favorite')
