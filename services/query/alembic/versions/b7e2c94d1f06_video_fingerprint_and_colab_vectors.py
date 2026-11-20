"""video fingerprint and colab vectors (OMNI-X05)

Revision ID: b7e2c94d1f06
Revises: 9b4e6d2a7c31
Create Date: 2026-11-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2c94d1f06'
down_revision: Union[str, Sequence[str], None] = '9b4e6d2a7c31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('videos', sa.Column('fingerprint', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_videos_fingerprint'), 'videos', ['fingerprint'], unique=False)
    op.add_column(
        'videos', sa.Column('colab_vectors', sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('videos', 'colab_vectors')
    op.drop_index(op.f('ix_videos_fingerprint'), table_name='videos')
    op.drop_column('videos', 'fingerprint')
