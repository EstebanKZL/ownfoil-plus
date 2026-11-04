"""Add the wishlist: the games each user wants

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3

One row per user and title id. Upcoming releases shows a user's wishlist first; a user
deleted takes their wishlist with them.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f9a0b1c2d3e4'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'wishlist',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title_id', sa.String(16), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'title_id', name='uq_wishlist_user_title'),
    )
    op.create_index('ix_wishlist_user_id', 'wishlist', ['user_id'])


def downgrade():
    op.drop_index('ix_wishlist_user_id', table_name='wishlist')
    op.drop_table('wishlist')
