"""Query tests run against a database of their own, never the stack's (K-18).

Several tests clean up by deleting every video. On the stack's database that would take
the loaded dataset footage with it (OMNI-608), so `POSTGRES_DB` is pointed at
`omnisight_test` before the app is imported (an environment variable wins over `.env`),
and that database is created if missing and migrated to head once per run. Same Postgres
server, so it still needs `docker compose up -d`.
"""

import os
import sys
from pathlib import Path

QUERY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUERY_DIR))

TEST_DB = "omnisight_test"
os.environ["POSTGRES_DB"] = TEST_DB


def _prepare_test_database() -> None:
    from alembic import command
    from alembic.config import Config
    from app.settings import settings
    from sqlalchemy import create_engine, text

    assert settings.postgres_db == TEST_DB, "tests must never run on the stack's database"
    admin = create_engine(settings.database_url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": TEST_DB}) is None:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()
    command.upgrade(Config(str(QUERY_DIR / "alembic.ini")), "head")


_prepare_test_database()
