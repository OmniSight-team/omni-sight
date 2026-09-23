"""add admission_reason to segments

Revision ID: 70d0558e7c6f
Revises: 3f193aff9b39
Create Date: 2026-09-23 13:41:02.301239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '70d0558e7c6f'
down_revision: Union[str, Sequence[str], None] = '3f193aff9b39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# CREATE TABLE compiles CREATE TYPE automatically for an enum column; ALTER
# TABLE ADD COLUMN (autogenerate's own first draft of this migration) does
# not — it assumes the type already exists and fails with "type
# admission_reason does not exist". The type is created explicitly here
# instead, with create_type=False on the column itself so add_column doesn't
# also try to create it a second time.
admission_reason_enum = postgresql.ENUM("motion", "heartbeat", name="admission_reason")


def upgrade() -> None:
    """Upgrade schema."""
    admission_reason_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'segments',
        sa.Column('admission_reason', postgresql.ENUM("motion", "heartbeat", name="admission_reason", create_type=False), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('segments', 'admission_reason')
    # drop_column leaves the enum type behind, which makes the next upgrade
    # fail with "type already exists" (same lesson as 2424eac9d88a).
    admission_reason_enum.drop(op.get_bind(), checkfirst=True)
