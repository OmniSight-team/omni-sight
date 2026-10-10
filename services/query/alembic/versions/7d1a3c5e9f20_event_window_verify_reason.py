"""event window verify reason

Revision ID: 7d1a3c5e9f20
Revises: 5c0e2f7a9b13
Create Date: 2026-10-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d1a3c5e9f20'
down_revision: Union[str, Sequence[str], None] = '5c0e2f7a9b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # OMNI-609: a window marked Wrong in the hand check says why.
    op.add_column('event_windows', sa.Column('verify_reason', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('event_windows', 'verify_reason')
