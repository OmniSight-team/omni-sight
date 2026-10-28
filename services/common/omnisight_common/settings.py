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
    # OMNI-503: each live camera's current frame, `{previews_path}/camera-{id}.jpg`.
    # Ingestion writes it, query serves it; the same path on both sides.
    previews_path: str = "/data/previews"

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

    # Qdrant (OMNI-703). Here because ai_workers writes vectors and query searches
    # them, and both must agree on the store and the collection. Not published to
    # the host: inside the stack it is reached as `qdrant` (QDRANT_HOST).
    qdrant_host: str = "127.0.0.1"
    qdrant_port: int = 6333
    qdrant_timeout_s: float = 10.0
    # Overridable so a test can use a collection of its own (OMNI-703's TC-3 does).
    frame_collection: str = "frame_vectors"

    # OMNI-704: Algorithm 2's frame encoder (Phase A §3.5.2), pinned to one revision so
    # this machine and Colab run the same weights (D-30). Changing either is a new model:
    # the stored vectors would no longer be comparable with new ones. Here since OMNI-705:
    # ai_workers writes vectors of this model, and query counts (and will search) only
    # vectors of this model.
    frame_model_id: str = "google/siglip2-so400m-patch14-384"
    frame_model_revision: str = "e8e487298228002f3d8a82e0cd5c8ea9c567f57f"
    # OMNI-706: Algorithm 2's clip encoder and Algorithm 3's second text encoder, pinned the
    # same way (D-33). Clip vectors are made on Colab (D-32) and searched here with this
    # model's text side, so both must be this exact revision.
    clip_model_id: str = "OpenGVLab/InternVideo2_CLIP_S"
    clip_model_revision: str = "1f9fca1389fd883defc652634d95a21121c85a8c"

    # OMNI-705: admitted frames waiting for a vector. The consumer publishes one job per
    # admitted frame after its row commits; ai_workers acknowledges it after the upsert.
    embed_queue: str = "omnisight.embed"
