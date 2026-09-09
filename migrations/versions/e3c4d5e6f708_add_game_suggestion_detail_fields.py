"""add play_style, system_requirements, notes to game_suggestions

Revision ID: e3c4d5e6f708
Revises: d2b3c4d5e6f7
Create Date: 2026-09-09 12:52:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e3c4d5e6f708'
down_revision = 'd2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('game_suggestions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('play_style', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('system_requirements', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('game_suggestions', schema=None) as batch_op:
        batch_op.drop_column('notes')
        batch_op.drop_column('system_requirements')
        batch_op.drop_column('play_style')
