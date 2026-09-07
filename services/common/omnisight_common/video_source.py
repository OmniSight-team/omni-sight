from enum import StrEnum


class VideoSource(StrEnum):
    UPLOAD = "upload"
    CAMERA = "camera"
    DATASET = "dataset"
