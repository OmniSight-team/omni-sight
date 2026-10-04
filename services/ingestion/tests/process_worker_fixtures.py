"""Workers for `test_worker_process.py` to build in a child process (OMNI-510a).

`ProcessWorker` builds its worker in the child from a "module:function" name, so
these must be importable there: the test puts this folder and services/ingestion
on the child's path. Each is a real `LiveWorker` over a scripted stream (25 frames
a second in real time) and a publisher that keeps nothing, so no camera and no
broker are needed.
"""

import tempfile
import time
from pathlib import Path

import numpy as np
from app.live_capture import Backoff, LiveWorker
from app.pipeline import FrameGate, FrameSource, GateDecision, process_frame


class PacedCapture:
    def __init__(self, open_ok=True):
        self._open_ok = open_ok
        self.delivered = 0
        self._released = False

    def isOpened(self):
        return self._open_ok

    def grab(self):
        if self._released:
            return False
        time.sleep(0.04)
        self.delivered += 1
        return True

    def retrieve(self):
        frame = np.full((48, 64, 3), 40, dtype=np.uint8)
        frame[10:20, (self.delivered * 2) % 50: (self.delivered * 2) % 50 + 10] = (0, 200, 255)
        return True, frame

    def release(self):
        self._released = True


class NullPublisher:
    def publish(self, record):
        pass

    def publish_event(self, *args, **kwargs):
        pass

    def publish_stats(self, report):
        pass

    def backlog(self):
        return 0

    def keepalive(self):
        pass

    def close(self):
        pass


class EveryOtherGate(FrameGate):
    def __init__(self):
        self.seen = 0

    def evaluate(self, frame, timestamp_s):
        self.seen += 1
        admitted = self.seen % 2 == 0
        return GateDecision(
            motion_score=1.0, admitted=admitted,
            clip_start_s=timestamp_s - 1.0 if admitted else None, clip_end_s=timestamp_s if admitted else None,
            admission_reason="motion" if admitted else None,
        )


def _worker(camera_id, open_ok):
    folder = Path(tempfile.mkdtemp())

    def make_process():
        gate = EveryOtherGate()

        def process(frame, timestamp_s, index):
            return process_frame(
                frame, FrameSource(source_type="camera", frame_index=index, timestamp_s=timestamp_s, camera_id=camera_id),
                gate, folder, folder, thumb_width=32, frame_quality=80, thumb_quality=60,
            )

        return process

    return LiveWorker(
        camera_id,
        open_capture=lambda: PacedCapture(open_ok=open_ok),
        make_publisher=NullPublisher,
        make_process=make_process,
        backoff=Backoff(60, 60),
    )


def steady_worker(camera_id, rtsp_url):
    return _worker(camera_id, open_ok=True)


def dead_stream_worker(camera_id, rtsp_url):
    return _worker(camera_id, open_ok=False)
