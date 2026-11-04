"""Add each user's own preferences: console firmware and Library background

Revision ID: e8f9a0b1c2d3
Revises: d5e6f7a8b9c0

Both live on the user row and are set from My account (/account):
- console_firmware: the firmware of the user's console, as 23.0.1. Games and updates
  that need a newer one are marked. Empty for a user who never set it.
- show_background_image: the Library list view's background art for this user. Empty
  means "as the server says" (Settings > Library > Organizer).
"""
from alembic import op
import sqlalchemy as sa


revision = 'e8f9a0b1c2d3'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('console_firmware', sa.String(16), nullable=True))
        batch_op.add_column(sa.Column('show_background_image', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('show_background_image')
        batch_op.drop_column('console_firmware')
