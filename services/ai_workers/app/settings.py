from omnisight_common import CommonSettings
from pydantic import Field


class Settings(CommonSettings):
    app_name: str = "omnisight-ai-workers"

    # The pinned checkpoint itself (`frame_model_id`, `frame_model_revision`) is in
    # CommonSettings since OMNI-705: query counts the vectors of that model only.
    # Where the checkpoint's files are kept (`models/pretrained/`, never committed),
    # downloaded at the pinned revision on the first start if missing.
    frame_model_dir: str = "/models/pretrained/siglip2-so400m-patch14-384"
    # OMNI-706: InternVideo2's checkpoint (`clip_model_id` / `clip_model_revision` in
    # CommonSettings). This service loads only its text side (D-32): the video side does
    # not fit beside SigLIP 2 here, and clip vectors are made on Colab.
    clip_model_dir: str = "/models/pretrained/internvideo2-clip-s"

    # OMNI-705: the embed queue's consumer. At most this many frames are encoded together
    # (also the broker's prefetch, so it never holds more than one batch unacknowledged).
    # A batch closes when it is full or when no further job arrives within the wait.
    embed_batch_size: int = Field(8, ge=1)
    embed_batch_wait_s: float = Field(0.5, gt=0)
    # Off for a process that only serves text queries.
    embed_consumer_enabled: bool = True


settings = Settings()
