from enum import StrEnum


class CameraStatus(StrEnum):
    REGISTERED = "registered"
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"
