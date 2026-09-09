"""add collect_emergency_contacts to events

Revision ID: c1a2b3d4e5f6
Revises: b265c4afc066
Create Date: 2026-09-09 12:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1a2b3d4e5f6'
down_revision = 'b265c4afc066'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'collect_emergency_contacts', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ))


def downgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('collect_emergency_contacts')
