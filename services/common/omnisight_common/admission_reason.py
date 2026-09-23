from enum import StrEnum


class AdmissionReason(StrEnum):
    """Why a segment was admitted. NULL on a segment that was not admitted at
    all — there is nothing to name a reason for."""

    MOTION = "motion"
    HEARTBEAT = "heartbeat"
