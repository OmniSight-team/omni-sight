"""TC-3, frame half (OMNI-703): 1,000 vectors with payloads into Qdrant, read back by id and
by filtered search, every field compared; then Qdrant restarted and everything compared again.

Qdrant publishes no port to the host, so the checks run inside `query` (which reaches it as
`qdrant`) and this script, run on the host, drives them and the restart:

    docker compose up -d
    uv run python scripts/verify_tc3_frame_vectors.py

1. `write` (in query): a scratch collection `frame_vectors_tc3`, made by the product's own
   `ensure_frame_collection`, gets 1,000 points built by `frame_point` from a fixed seed:
   half uploads (5 videos), half live frames (10 cameras), all three domains, some without a
   thumbnail. The first 100 are then written again (a redelivery): the count must stay 1,000.
   Then `check`.
2. `docker compose restart qdrant`, wait until healthy.
3. `check` again, then the scratch collection is dropped.

`check`: the count; the three payload indexes; every point by id, its payload equal to the
expected one as a dict and as canonical JSON bytes, its vector equal to the expected float32
vector; every point found again as the top hit of a search with its own vector, filtered by
its video or camera and by its exact `captured_at`, with the same payload; the point count
under each video and camera filter. The real `frame_vectors` is only checked to exist.
Rerunnable; the points are regenerated from the seed, so nothing is carried between stages.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

COLLECTION = "frame_vectors_tc3"
POINTS = 1000
REDELIVERED = 100
SEED = 703
BATCH = 100


# --- inside query ---------------------------------------------------------------------------


def _expected():
    import numpy as np
    from datetime import UTC, datetime

    from omnisight_common.domain import Domain
    from omnisight_common.frame_vectors import FRAME_VECTOR_SIZE, FramePayload, captured_at
    from omnisight_common.segment_source_type import SegmentSourceType

    rng = np.random.default_rng(SEED)
    domains = list(Domain)
    uploaded_at = datetime(2026, 10, 19, 9, 5, 39, 417_000, tzinfo=UTC)
    points = []
    for i in range(POINTS):
        segment_id = 1_000_001 + i
        vector = rng.standard_normal(FRAME_VECTOR_SIZE).astype(np.float32)
        vector /= np.linalg.norm(vector)
        if i % 2 == 0:
            source, video_id, camera_id = SegmentSourceType.UPLOAD, 3226 + i % 5, None
            # Not a round number: fractions must survive the round trip exactly.
            timestamp_s = (i // 2) / 23.976
            at = captured_at(source, timestamp_s, uploaded_at)
            folder = f"{video_id}"
        else:
            source, video_id, camera_id = SegmentSourceType.CAMERA, None, 1 + i % 10
            # A full-precision fraction, as `time.time()` gives.
            timestamp_s = 1_760_864_401.0 + i * 0.2003 + float(rng.random()) * 1e-3
            at = captured_at(source, timestamp_s, None)
            folder = f"camera-{camera_id}"
        payload = FramePayload(
            segment_id=segment_id,
            video_id=video_id,
            camera_id=camera_id,
            source_type=source,
            domain=domains[i % len(domains)],
            timestamp_s=timestamp_s,
            captured_at=at,
            frame_path=f"/data/frames/{folder}/{i:06d}.jpg",
            thumb_path=None if i % 7 == 0 else f"/data/thumbs/{folder}/{i:06d}.jpg",
            model="google/siglip2-so400m-patch14-384",
            model_revision="tc3",
        )
        points.append((payload, vector))
    return points


def _client():
    from omnisight_common.frame_vectors import qdrant_client
    from omnisight_common.settings import CommonSettings

    return qdrant_client(CommonSettings())


def _write() -> int:
    from omnisight_common.frame_vectors import ensure_frame_collection, frame_point

    client = _client()
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    assert ensure_frame_collection(client, COLLECTION), "the scratch collection was not created"
    points = _expected()
    started = time.perf_counter()
    for start in range(0, POINTS, BATCH):
        batch = points[start : start + BATCH]
        client.upsert(COLLECTION, [frame_point(p, v.tolist()) for p, v in batch], wait=True)
    print(f"wrote {POINTS} points in {time.perf_counter() - started:.2f} s")
    # A redelivery: the same segments again. Same ids, so the same points.
    client.upsert(COLLECTION, [frame_point(p, v.tolist()) for p, v in points[:REDELIVERED]], wait=True)
    print(f"wrote the first {REDELIVERED} again")
    assert not ensure_frame_collection(client, COLLECTION), "an existing collection was created again"
    client.close()
    return _check(drop=False)


def _check(drop: bool) -> int:
    import numpy as np
    from qdrant_client import models

    from omnisight_common.frame_vectors import PAYLOAD_INDEXES

    client = _client()
    failures: list[str] = []

    def fail(message: str) -> None:
        failures.append(message)
        if len(failures) <= 10:
            print("FAIL:", message)

    points = _expected()
    expected = {p.segment_id: (p.model_dump(mode="json"), v) for p, v in points}

    info = client.get_collection(COLLECTION)
    params = info.config.params.vectors
    if (params.size, params.distance) != (1152, models.Distance.COSINE):
        fail(f"collection shape {params.size} {params.distance}")
    for field, schema in PAYLOAD_INDEXES.items():
        got = info.payload_schema.get(field)
        if got is None or got.data_type != schema:
            fail(f"payload index on {field}: {got}")
    count = client.count(COLLECTION, exact=True).count
    if count != POINTS:
        fail(f"count {count}, expected {POINTS}")

    # By id.
    ids = list(expected)
    max_diff, exact_vectors = 0.0, 0
    for start in range(0, len(ids), BATCH):
        got = client.retrieve(COLLECTION, ids[start : start + BATCH], with_payload=True, with_vectors=True)
        if len(got) != len(ids[start : start + BATCH]):
            fail(f"retrieve returned {len(got)} of {BATCH} from {ids[start]}")
        for point in got:
            payload, vector = expected[point.id]
            if point.payload != payload:
                fail(f"payload of {point.id} differs: {point.payload} != {payload}")
            if json.dumps(point.payload, sort_keys=True) != json.dumps(payload, sort_keys=True):
                fail(f"payload bytes of {point.id} differ")
            stored = np.asarray(point.vector, dtype=np.float32)
            diff = float(np.max(np.abs(stored - vector)))
            max_diff = max(max_diff, diff)
            exact_vectors += bool(np.array_equal(stored, vector))
            if diff > 1e-6:
                fail(f"vector of {point.id} differs by {diff}")
    print(f"by id: {len(ids)} points, payloads compared; vectors bit-identical {exact_vectors}, max |diff| {max_diff:.2e}")

    # By filtered search: each point is the top hit for its own vector under its own filter.
    found = 0
    for segment_id, (payload, vector) in expected.items():
        source = (
            models.FieldCondition(key="video_id", match=models.MatchValue(value=payload["video_id"]))
            if payload["video_id"] is not None
            else models.FieldCondition(key="camera_id", match=models.MatchValue(value=payload["camera_id"]))
        )
        moment = models.FieldCondition(
            key="captured_at", range=models.DatetimeRange(gte=payload["captured_at"], lte=payload["captured_at"])
        )
        hits = client.query_points(
            COLLECTION, query=vector.tolist(), query_filter=models.Filter(must=[source, moment]), limit=1, with_payload=True
        ).points
        if not hits or hits[0].id != segment_id:
            fail(f"filtered search for {segment_id} returned {[h.id for h in hits]}")
        elif hits[0].payload != payload:
            fail(f"filtered search payload of {segment_id} differs")
        else:
            found += 1
    print(f"filtered search: {found} of {POINTS} found as their own top hit, payload equal")

    # Counts under each filter, from the payload indexes.
    for key, values in (("video_id", range(3226, 3231)), ("camera_id", range(1, 11))):
        for value in values:
            want = sum(1 for p, _ in expected.values() if p[key] == value)
            got = client.count(
                COLLECTION,
                count_filter=models.Filter(must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))]),
                exact=True,
            ).count
            if got != want:
                fail(f"{key}={value}: {got} points, expected {want}")
    print("filter counts: 5 videos, 10 cameras compared")

    from omnisight_common.settings import CommonSettings

    real = CommonSettings().frame_collection
    if not client.collection_exists(real):
        fail(f"{real} does not exist (query creates it at startup)")
    else:
        print(f"{real} exists")

    if drop:
        client.delete_collection(COLLECTION)
        print(f"dropped {COLLECTION}")
    client.close()
    print("PASS" if not failures else f"FAIL: {len(failures)} problems")
    return 0 if not failures else 1


# --- on the host ----------------------------------------------------------------------------


def _in_query(stage: str) -> int:
    source = Path(__file__).read_bytes()
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", stage],
        input=source,
    ).returncode


def _wait_healthy(service: str, timeout_s: float = 120) -> float:
    container = subprocess.run(
        ["docker", "compose", "ps", "-q", service], capture_output=True, text=True, check=True
    ).stdout.strip()
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        status = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container], capture_output=True, text=True
        ).stdout.strip()
        if status == "healthy":
            return time.monotonic() - started
        time.sleep(1)
    raise SystemExit(f"{service} not healthy after {timeout_s} s")


def main() -> int:
    print("== before the restart ==", flush=True)
    if _in_query("write") != 0:
        return 1
    print("== docker compose restart qdrant ==", flush=True)
    subprocess.run(["docker", "compose", "restart", "qdrant"], check=True)
    print(f"healthy again after {_wait_healthy('qdrant'):.1f} s", flush=True)
    print("== after the restart ==", flush=True)
    return _in_query("check")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else None
    if stage == "write":
        sys.exit(_write())
    if stage == "check":
        sys.exit(_check(drop=True))
    sys.exit(main())
