import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "query"))

from app.db import SessionLocal
from app.models import Video
from app.settings import settings
from sqlalchemy import update


def backfill_retention() -> int:
    """Fill retention_until = created_at + VIDEO_RETENTION_DAYS on every video
    row where it is still NULL. Only NULL rows are touched, so running it a
    second time changes nothing.

    Note the date is counted from each row's own created_at, not from today:
    a recording uploaded more than VIDEO_RETENTION_DAYS ago comes out already
    expired, and the slice-16 retention job will treat it that way."""
    with SessionLocal() as session:
        result = session.execute(
            update(Video)
            .where(Video.retention_until.is_(None))
            .values(retention_until=Video.created_at + timedelta(days=settings.video_retention_days))
        )
        session.commit()
        return result.rowcount


if __name__ == "__main__":
    updated = backfill_retention()
    print(f"backfilled retention_until on {updated} video(s), {settings.video_retention_days} days")
