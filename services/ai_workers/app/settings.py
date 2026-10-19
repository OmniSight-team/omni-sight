from omnisight_common import CommonSettings


class Settings(CommonSettings):
    app_name: str = "omnisight-ai-workers"

    # OMNI-704: Algorithm 2's frame encoder (Phase A §3.5.2), pinned to one revision so
    # this machine and Colab run the same weights (D-30). Changing either is a new model:
    # the stored vectors would no longer be comparable with new ones.
    frame_model_id: str = "google/siglip2-so400m-patch14-384"
    frame_model_revision: str = "e8e487298228002f3d8a82e0cd5c8ea9c567f57f"
    # Where the checkpoint's files are kept (`models/pretrained/`, never committed),
    # downloaded at the pinned revision on the first start if missing.
    frame_model_dir: str = "/models/pretrained/siglip2-so400m-patch14-384"


settings = Settings()
