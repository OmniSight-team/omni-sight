from typing import Literal

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
    # OMNI-312: starting a camera waits for a reachability check (up to ~18 s),
    # then for the stream to open and deliver its first frame (ingestion allows
    # 30 s); stopping waits for the worker to release its stream (up to 15 s).
    # Both longer than the calls they wait on.
    ingestion_worker_start_timeout_s: float = Field(70.0, gt=0)
    ingestion_worker_stop_timeout_s: float = Field(30.0, gt=0)
    # OMNI-504: asking ingestion which workers it runs is quick, or it is down.
    ingestion_workers_timeout_s: float = Field(3.0, gt=0)

    # OMNI-504: a camera is `live` when its newest frame (the preview's write
    # time, OMNI-503) is at most this old; older, with the worker still reading,
    # it is `frozen`. The preview is rewritten every 0.5 s on a healthy feed.
    live_stale_after_s: float = Field(3.0, gt=0)
    # OMNI-504: how often query checks that every camera with `capture_enabled`
    # has a worker, and starts the ones that do not (after an ingestion restart,
    # say). 0 turns it off. A camera whose start fails is tried again after a
    # wait that doubles up to the maximum, so a dead camera is not hammered.
    capture_resume_interval_s: float = Field(5.0, ge=0)
    capture_resume_max_backoff_s: float = Field(60.0, gt=0)

    # OMNI-311: how many unacknowledged segments one consumer may hold at once.
    # Without a limit the broker hands a single consumer the whole backlog, so a
    # second consumer would sit idle while the first works through it.
    segment_prefetch: int = Field(10, ge=1)
    # OMNI-502: which segments this consumer process stores. "files" reads the
    # file queue (`segment_queue`) and the camera queue (status changes and
    # stats); "live" reads the live queue (`live_segment_queue`) only. Two
    # services in docker-compose.yml, one of each, same image and code, so a
    # recording being stored never delays a live frame.
    consumer_role: Literal["files", "live"] = "files"
    # OMNI-313: a stored live frame refreshes its camera's `last_seen_at`, but no
    # more than once in this many seconds. Updating it on every frame would be a
    # write to one row five times a second per camera for a number nobody reads
    # that finely; a camera going quiet is caught by a status event, not by this.
    camera_last_seen_interval_s: float = Field(5.0, ge=0)
    # OMNI-314: a live worker reports its counters every few seconds. A camera
    # whose last report is older than this is treated as not running, so its
    # uptime and effective rate read as zero instead of a frozen last value.
    camera_stats_stale_s: float = Field(20.0, gt=0)
    # An extraction is finished when every segment ingestion published has been
    # stored by the consumer. This is how long to wait for that — long enough to
    # ride out a consumer restart, short enough that a consumer that is gone
    # for good does not leave the video `extracting` forever.
    extraction_commit_timeout_s: float = Field(600.0, gt=0)
    extraction_poll_s: float = Field(0.25, gt=0)

    video_storage_path: str = "/data/videos"
    max_upload_size_mb: int = 500
    # OMNI-608: the local dataset mirror (`data/`), mounted read-only. Dataset footage
    # is read from here and goes through the same upload path as any file.
    datasets_path: str = "/datasets"
    # OMNI-608, D-26: the committed hand-check sample, the only dataset clips loaded.
    hand_check_sample_path: str = "/hand_check/sample.csv"

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
