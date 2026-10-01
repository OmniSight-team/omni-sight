"""add capture_enabled to cameras

Revision ID: d4865a17f560
Revises: 1108fdad7cf9
Create Date: 2026-10-02 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4865a17f560'
down_revision: Union[str, Sequence[str], None] = '1108fdad7cf9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # OMNI-504: whether a camera should be captured, so capture can be resumed
    # after ingestion restarts. False for every existing camera: nothing is known
    # to have been started before this column existed.
    op.add_column('cameras', sa.Column('capture_enabled', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('cameras', 'capture_enabled')
