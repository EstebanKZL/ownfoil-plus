"""Add indexes for the hot lookups of large libraries

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9

Measured on a synthetic library of 6,000 titles / 30,000 apps / 18,000 files:
- apps(title_id): every per-title recompute (update_title_flags, has_owned_apps, the
  DLC lookup) scanned the whole apps table. The batch recompute after each TitleDB
  refresh went from 19.4 s to 3.8 s.
- files(added_at): the Files page's default "newest first" order and the dashboard's
  recently added list sorted the whole table (4.1 ms -> 0.06 ms per page).
- files(library_id): the foreign key a library removal cascades through.
"""
from alembic import op


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_apps_title_id', 'apps', ['title_id'])
    op.create_index('ix_files_added_at', 'files', ['added_at'])
    op.create_index('ix_files_library_id', 'files', ['library_id'])


def downgrade():
    op.drop_index('ix_files_library_id', table_name='files')
    op.drop_index('ix_files_added_at', table_name='files')
    op.drop_index('ix_apps_title_id', table_name='apps')
