"""Identify again the files a bad migration left without their game

Revision ID: d0e1f2a3b4c7
Revises: c9d0e1f2a3b6

The first version of c9d0e1f2a3b6 rebuilt `files` and, through the foreign keys, emptied
`app_files`: every file stayed "identified" but pointed at no game. An identified file
always points at one, so any that doesn't is marked unidentified here, and the next scan
identifies it again - its game, cover and counts come back. Marked 'relink', it is
not announced as a new file (no "file added" message for a library already there). Nothing else is touched; on a
library that was never hit it changes nothing.
"""
from alembic import op


revision = 'd0e1f2a3b4c7'
down_revision = 'c9d0e1f2a3b6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE files SET identified = 0, identification_attempts = 0, identification_type = 'relink' "
        "WHERE identified = 1 AND id NOT IN (SELECT file_id FROM app_files)")


def downgrade():
    pass
