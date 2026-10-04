"""gate counters on camera_stats

Revision ID: 1108fdad7cf9
Revises: 08b81a0fd8d1
Create Date: 2026-09-30 12:22:27.678104

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1108fdad7cf9'
down_revision: Union[str, Sequence[str], None] = '08b81a0fd8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# OMNI-501: a live camera stores admitted frames only, so what the gate did with
# every frame is kept as counters. Each has a `session_` twin, as `captured` and
# `dropped` already do.
COUNTERS = ('gated', 'admitted_motion', 'admitted_heartbeat', 'discarded')


def upgrade() -> None:
    """Upgrade schema."""
    for counter in COUNTERS:
        op.add_column('camera_stats', sa.Column(counter, sa.BigInteger(), server_default='0', nullable=False))
    for counter in COUNTERS:
        op.add_column('camera_stats', sa.Column(f'session_{counter}', sa.BigInteger(), server_default='0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    for counter in reversed(COUNTERS):
        op.drop_column('camera_stats', f'session_{counter}')
    for counter in reversed(COUNTERS):
        op.drop_column('camera_stats', counter)
