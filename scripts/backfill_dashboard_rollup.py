"""Backfill the dashboard's rollup for segment rows written before it existed (OMNI-610).

The triggers on `segments` (D-28) keep `segment_hourly` exact from the migration on, and
the migration counts the rows already there, but it cannot see the disk: their
`file_bytes` is 0. This:

  1. fills `file_bytes` on every row that points at a frame or thumbnail and still has 0,
     from the size of the files on disk (a missing file counts 0 and is reported);
  2. rebuilds `segment_hourly` from `segments` in one transaction, with `segments` locked
     against writes (SHARE mode) so no row can land between the count and the commit;
  3. prints the rollup's totals next to a direct count, which must be equal.

Rerunnable: step 1 skips rows already filled, step 2 replaces the rollup rather than
adding to it. Run it inside `query`, which mounts the frame and thumbnail volumes:

    docker compose exec -T -e PYTHONPATH=services/query query \\
        uv run --package omnisight-query python - < scripts/backfill_dashboard_rollup.py
"""

import sys
from pathlib import Path

# Run from a file, find `app` beside it; piped in on stdin, PYTHONPATH says where.
if "__file__" in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "query"))

from app.db import SessionLocal
from sqlalchemy import text

BATCH = 1000


def _size(path: str | None) -> tuple[int, bool]:
    if path is None:
        return 0, False
    try:
        return Path(path).stat().st_size, False
    except FileNotFoundError:
        return 0, True


def fill_file_bytes() -> tuple[int, int]:
    """Returns how many rows were filled and how many files were missing."""
    filled = missing = 0
    last_id = 0
    with SessionLocal() as db:
        while True:
            rows = db.execute(
                text(
                    "SELECT id, frame_path, thumb_path FROM segments "
                    "WHERE id > :last AND file_bytes = 0 "
                    "AND (frame_path IS NOT NULL OR thumb_path IS NOT NULL) "
                    "ORDER BY id LIMIT :n"
                ),
                {"last": last_id, "n": BATCH},
            ).all()
            if not rows:
                return filled, missing
            values = []
            for row in rows:
                frame, frame_missing = _size(row.frame_path)
                thumb, thumb_missing = _size(row.thumb_path)
                missing += frame_missing + thumb_missing
                if frame + thumb:
                    values.append({"id": row.id, "b": frame + thumb})
            if values:
                db.execute(text("UPDATE segments SET file_bytes = :b WHERE id = :id"), values)
                filled += len(values)
            db.commit()
            last_id = rows[-1].id


def rebuild_rollup() -> None:
    with SessionLocal() as db:
        db.execute(text("LOCK TABLE segments IN SHARE MODE"))
        db.execute(text("DELETE FROM segment_hourly"))
        db.execute(
            text(
                "INSERT INTO segment_hourly (hour, source_type, segments, admitted, file_bytes) "
                "SELECT date_trunc('hour', created_at, 'UTC'), source_type, count(*), "
                "count(*) FILTER (WHERE admitted), coalesce(sum(file_bytes), 0) "
                "FROM segments GROUP BY 1, 2"
            )
        )
        db.commit()


def compare() -> tuple[tuple, tuple]:
    with SessionLocal() as db:
        rollup = db.execute(
            text(
                "SELECT coalesce(sum(segments), 0), coalesce(sum(admitted), 0), "
                "coalesce(sum(file_bytes), 0) FROM segment_hourly"
            )
        ).one()
        direct = db.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE admitted), coalesce(sum(file_bytes), 0) "
                "FROM segments"
            )
        ).one()
    return tuple(rollup), tuple(direct)


if __name__ == "__main__":
    filled, missing = fill_file_bytes()
    print(f"file_bytes filled on {filled} row(s); {missing} file(s) missing on disk")
    rebuild_rollup()
    rollup, direct = compare()
    print(f"rollup  segments={rollup[0]} admitted={rollup[1]} file_bytes={rollup[2]}")
    print(f"direct  segments={direct[0]} admitted={direct[1]} file_bytes={direct[2]}")
    print("equal" if rollup == direct else "NOT EQUAL")
    sys.exit(0 if rollup == direct else 1)
