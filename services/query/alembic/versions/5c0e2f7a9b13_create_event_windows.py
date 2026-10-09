"""create event_windows

Revision ID: 5c0e2f7a9b13
Revises: 48f90770010b
Create Date: 2026-10-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5c0e2f7a9b13'
down_revision: Union[str, Sequence[str], None] = '48f90770010b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # OMNI-607: lead-up windows derived from the manifest's events, and normal videos.
    op.create_table(
        'event_windows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('manifest_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('nominal_length_s', sa.Float(), nullable=True),
        sa.Column('window_start_s', sa.Float(), nullable=False),
        sa.Column('window_end_s', sa.Float(), nullable=False),
        sa.Column('length_s', sa.Float(), nullable=False),
        sa.Column('shortened', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('event_class', sa.String(), nullable=False),
        sa.Column('domain', postgresql.ENUM(name='domain', create_type=False), nullable=False),
        sa.Column('split', sa.String(), nullable=False),
        sa.Column('derived', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('verified', sa.Boolean(), nullable=True),
        sa.Column('verified_by', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('window_start_s >= 0 AND window_end_s > window_start_s', name='ck_event_windows_bounds'),
        sa.ForeignKeyConstraint(['manifest_id'], ['dataset_manifest.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['verified_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'manifest_id', 'kind', 'nominal_length_s', name='uq_event_windows_window', postgresql_nulls_not_distinct=True
        ),
    )
    op.create_index(op.f('ix_event_windows_manifest_id'), 'event_windows', ['manifest_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_event_windows_manifest_id'), table_name='event_windows')
    op.drop_table('event_windows')
