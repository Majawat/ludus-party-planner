"""add event_date to potluck_items

Revision ID: d2b3c4d5e6f7
Revises: c1a2b3d4e5f6
Create Date: 2026-09-09 12:51:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd2b3c4d5e6f7'
down_revision = 'c1a2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('potluck_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('potluck_items', schema=None) as batch_op:
        batch_op.drop_column('event_date')
