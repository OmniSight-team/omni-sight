from omnisight_common import CommonSettings
from pydantic import Field


class Settings(CommonSettings):
    app_name: str = "omnisight-query"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    admin_email: str
    admin_password: str

    jwt_secret_key: str
    access_token_expire_minutes: int = 15

    max_failed_attempts: int = 5
    account_lockout_minutes: int = 15

    frontend_origin: str = "http://localhost:3000"

    ingestion_base_url: str = "http://localhost:8001"
    # Extraction decodes a whole video inside one request to ingestion, so it
    # gets far longer than a probe does.
    ingestion_extract_timeout_s: float = Field(900.0, gt=0)
    # OMNI-308: a transcode, not a one-frame read like /probe/file — shorter
    # than extraction's own timeout (nothing here decodes every frame with a
    # motion gate), but still far longer than a plain probe needs.
    ingestion_playback_timeout_s: float = Field(150.0, gt=0)

    video_storage_path: str = "/data/videos"
    max_upload_size_mb: int = 500

    # ge=1: the slice-16 retention job deletes footage past this date, so a
    # zero or negative value would mark every new upload as already expired.
    video_retention_days: int = Field(30, ge=1)

    # OMNI-307: the URL path Nginx serves thumbnails from, straight off the
    # `thumb_storage` volume — never through this API. Must match
    # infra/nginx/default.conf's `location /thumbs/` block; nginx.conf has no
    # templating in this project, so the two are kept in sync by convention,
    # the same way the `/api` prefix already is across nginx, next.config.ts
    # and api-client.ts.
    thumb_url_prefix: str = "/thumbs"

    # OMNI-308: same idea, for video bytes — Nginx's `location /media/` block
    # serves straight off `video_storage`. Whichever of the original or the
    # playback copy is browser-playable, this is the prefix its URL uses.
    video_url_prefix: str = "/media"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
