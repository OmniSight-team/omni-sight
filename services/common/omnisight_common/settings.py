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
