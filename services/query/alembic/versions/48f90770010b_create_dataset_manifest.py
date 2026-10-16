"""create dataset_manifest

Revision ID: 48f90770010b
Revises: d4865a17f560
Create Date: 2026-10-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '48f90770010b'
down_revision: Union[str, Sequence[str], None] = 'd4865a17f560'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANNOTATION_SOURCES = ('ucf_crime_temporal', 'uca', 'ccd_binlabels', 'virat_events', 'normal', 'untimed')


def upgrade() -> None:
    """Upgrade schema."""
    # OMNI-604: one row per clip of every dataset, from its annotation files.
    op.create_table(
        'dataset_manifest',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset', sa.String(), nullable=False),
        sa.Column('clip_key', sa.String(), nullable=False),
        sa.Column('domain', postgresql.ENUM(name='domain', create_type=False), nullable=False),
        sa.Column('event_class', sa.String(), nullable=True),
        sa.Column('event_start_s', sa.Float(), nullable=True),
        sa.Column('event_end_s', sa.Float(), nullable=True),
        sa.Column('annotation_source', sa.Enum(*ANNOTATION_SOURCES, name='annotation_source'), nullable=False),
        sa.Column('split', sa.String(), nullable=True),
        sa.Column('video_id', sa.Integer(), nullable=True),
        sa.Column('video_relpath', sa.String(), nullable=False),
        sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset', 'clip_key', name='uq_dataset_manifest_clip'),
    )
    op.create_index(op.f('ix_dataset_manifest_dataset'), 'dataset_manifest', ['dataset'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_dataset_manifest_dataset'), table_name='dataset_manifest')
    op.drop_table('dataset_manifest')
    sa.Enum(name='annotation_source').drop(op.get_bind(), checkfirst=True)
