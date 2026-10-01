from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Where extracted frames and their thumbnails live: one sub-folder per video,
    # `{frames_path}/{video_id}/` and `{thumbs_path}/{video_id}/`. Here rather
    # than in either service because ingestion writes them and query deletes
    # them, and the two must never disagree about the layout.
    frames_path: str = "/data/frames"
    thumbs_path: str = "/data/thumbs"

    # RabbitMQ (OMNI-311). Here for the same reason as the paths above: ingestion
    # publishes and query consumes, and the two must agree on the broker and on
    # the queue's name. The credentials have no default — they come from `.env`.
    # An address, not "localhost": on Windows that resolves to IPv6 first, the
    # broker's published port is IPv4 only, and every connection then waits out a
    # failed attempt (about two seconds) before falling back.
    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = 5672
    rabbitmq_user: str
    rabbitmq_password: str
    # Overridable so a test can use a queue of its own instead of competing
    # with the real consumer for the real one.
    segment_queue: str = "omnisight.segments"
    # OMNI-502: live cameras' segments go through a queue of their own, read by a
    # consumer of their own, so a live frame never waits behind a recording's
    # burst of thousands (K-1, NFR-1). `segment_queue` above carries files only.
    live_segment_queue: str = "omnisight.segments.live"
    # OMNI-313: a camera going unreachable, or coming back, as the capture worker
    # notices it.
    camera_event_queue: str = "omnisight.camera_events"
