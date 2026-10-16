"""segment hourly rollup

Revision ID: 9b4e6d2a7c31
Revises: 7d1a3c5e9f20
Create Date: 2026-10-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9b4e6d2a7c31'
down_revision: Union[str, Sequence[str], None] = '7d1a3c5e9f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# OMNI-610 (D-28): one row per hour and source, kept by statement-level triggers on
# `segments`, so it changes in the same transaction as the rows it counts: the consumer's
# insert, a failed or replaced extraction's delete, a re-gate's update, a video's cascade.
# Each statement adds one aggregated upsert per (hour, source) it touched, read from its
# transition table. The hour is the row's `created_at` in UTC, whatever the session's
# time zone.
_DELTAS = """
    SELECT date_trunc('hour', created_at, 'UTC') AS hour, source_type,
           count(*) AS segments,
           count(*) FILTER (WHERE admitted) AS admitted,
           coalesce(sum(file_bytes), 0) AS file_bytes
    FROM {table} GROUP BY 1, 2
"""

_UPSERT = """
    INSERT INTO segment_hourly (hour, source_type, segments, admitted, file_bytes)
    SELECT hour, source_type, sum(segments), sum(admitted), sum(file_bytes)
    FROM ({deltas}) AS d
    GROUP BY hour, source_type
    HAVING sum(segments) <> 0 OR sum(admitted) <> 0 OR sum(file_bytes) <> 0
    ORDER BY hour, source_type
    ON CONFLICT (hour, source_type) DO UPDATE SET
        segments = segment_hourly.segments + EXCLUDED.segments,
        admitted = segment_hourly.admitted + EXCLUDED.admitted,
        file_bytes = segment_hourly.file_bytes + EXCLUDED.file_bytes;
"""

_ADDED = _DELTAS.format(table="new_rows")
_REMOVED = (
    "SELECT hour, source_type, -segments AS segments, -admitted AS admitted,"
    " -file_bytes AS file_bytes FROM ("
    + _DELTAS.format(table="old_rows")
    + ") AS o"
)

_FUNCTIONS = {
    "segment_hourly_on_insert": _UPSERT.format(deltas=_ADDED),
    "segment_hourly_on_delete": _UPSERT.format(deltas=_REMOVED),
    "segment_hourly_on_update": _UPSERT.format(deltas=_ADDED + " UNION ALL " + _REMOVED),
}


def upgrade() -> None:
    """Upgrade schema."""
    # The bytes of the frame and thumbnail JPEGs a row's frame wrote; 0 when it wrote none.
    op.add_column(
        'segments', sa.Column('file_bytes', sa.Integer(), server_default='0', nullable=False)
    )
    op.create_table(
        'segment_hourly',
        sa.Column('hour', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'source_type',
            postgresql.ENUM(name='segment_source_type', create_type=False),
            nullable=False,
        ),
        sa.Column('segments', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('admitted', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('file_bytes', sa.BigInteger(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('hour', 'source_type'),
    )
    for name, body in _FUNCTIONS.items():
        op.execute(
            f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            f"BEGIN\n{body}\nRETURN NULL;\nEND\n$$"
        )
    op.execute(
        "CREATE FUNCTION segment_hourly_on_truncate() RETURNS trigger LANGUAGE plpgsql AS $$\n"
        "BEGIN\nDELETE FROM segment_hourly;\nRETURN NULL;\nEND\n$$"
    )
    op.execute(
        "CREATE TRIGGER segment_hourly_insert AFTER INSERT ON segments "
        "REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT "
        "EXECUTE FUNCTION segment_hourly_on_insert()"
    )
    op.execute(
        "CREATE TRIGGER segment_hourly_delete AFTER DELETE ON segments "
        "REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT "
        "EXECUTE FUNCTION segment_hourly_on_delete()"
    )
    op.execute(
        "CREATE TRIGGER segment_hourly_update AFTER UPDATE ON segments "
        "REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT "
        "EXECUTE FUNCTION segment_hourly_on_update()"
    )
    op.execute(
        "CREATE TRIGGER segment_hourly_truncate AFTER TRUNCATE ON segments "
        "FOR EACH STATEMENT EXECUTE FUNCTION segment_hourly_on_truncate()"
    )
    # The rows already there are counted once, here, in the same transaction that creates
    # the triggers. Their `file_bytes` is 0 until scripts/backfill_dashboard_rollup.py reads
    # the files' sizes off the disk, which a migration cannot see.
    op.execute(
        "LOCK TABLE segments IN SHARE MODE;"
        "INSERT INTO segment_hourly (hour, source_type, segments, admitted, file_bytes) "
        "SELECT date_trunc('hour', created_at, 'UTC'), source_type, count(*), "
        "count(*) FILTER (WHERE admitted), 0 FROM segments GROUP BY 1, 2"
    )


def downgrade() -> None:
    """Downgrade schema."""
    for trigger in ('insert', 'delete', 'update', 'truncate'):
        op.execute(f"DROP TRIGGER segment_hourly_{trigger} ON segments")
        op.execute(f"DROP FUNCTION segment_hourly_on_{trigger}()")
    op.drop_table('segment_hourly')
    op.drop_column('segments', 'file_bytes')
