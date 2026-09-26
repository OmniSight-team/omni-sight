"""The definition of done for slices 3 and 4, run against the live stack (OMNI-319).

Checks, through the real API, database, broker and containers:

  A  a recording that is still and then moves: early frames discarded (heartbeat only),
     moving frames admitted
  B  moving the threshold changes the counts (re-gating the stored frames)
  C  a thumbnail carries the moment to seek to, and the thumbnail and the playback
     stream are served (the click itself is a browser check, not done here)
  D  a camera started against the simulator: frames arrive continuously, counters climb
  E  the simulator killed: the camera goes unreachable, then recovers on its own
  F  the worker restarted mid-capture, three ways, and nothing already accepted is lost:
       graceful  `docker compose restart ingestion`
       hard      `docker compose kill ingestion` (SIGKILL, no shutdown code runs)
       consumer  `docker compose stop consumer`, then start (the queue must hold the backlog)

"Accepted" means the broker confirmed the publish. For F the ground truth is the disk:
every frame the worker admits is written to /data/frames before it is published, so a
file on disk without a row is a frame that was never confirmed (allowed only at the very
end of a killed worker's last moments), and a gap in the middle of a session's frame
indexes, or a row whose file is missing, is a real loss.

Run from the repo root, in the background (it takes several minutes):

  PYTHONPATH=services/query nohup uv run --package omnisight-query \\
      python scripts/verify_definition_of_done.py > /tmp/dod319.txt 2>&1 &

`--only A,B,C` (letters) runs some of them. Everything it creates is removed at the end.
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
from itertools import pairwise
from pathlib import Path

import httpx
import pika
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User, Video
from app.security import hash_password
from omnisight_common import CommonSettings, Role, connection_parameters
from sqlalchemy import text

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--only", default="A,B,C,D,E,F", help="comma-separated letters of the checks to run")
parser.add_argument("--camera", default="cam02", help="the simulator feed to capture")
ARGS = parser.parse_args()
ONLY = {x.strip().upper() for x in ARGS.only.split(",")}
ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(tempfile.mkdtemp(prefix="omni-dod-"))
BASE = "http://127.0.0.1:8000"
NGINX = "https://localhost"  # serves /thumbs and /media, as the browser reaches them (self-signed)
EMAIL = "omni319-verify@omnisight.local"
PASSWORD = "Omni319Verify!"  # a throwaway account, deleted at the end
PREFIX = "omni319-"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
SETTINGS = CommonSettings()
RESULTS: list[tuple[str, bool, str]] = []


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def check(label: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""), flush=True)
    return ok


def queue_depth(queue: str) -> int:
    with pika.BlockingConnection(connection_parameters(SETTINGS)) as conn:
        return conn.channel().queue_declare(queue, passive=True).method.message_count


def wait_drained(timeout_s: float = 180) -> bool:
    deadline = time.time() + timeout_s
    calm = 0
    while time.time() < deadline:
        try:
            calm = calm + 1 if queue_depth(SETTINGS.segment_queue) == 0 else 0
        except Exception:  # noqa: BLE001 - the broker may be busy; ask again
            calm = 0
        if calm >= 3:
            return True
        time.sleep(1)
    return False


def ingestion_up(timeout_s: float = 90) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c",
                 "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health').status)")
        if out.stdout.strip() == "200":
            return True
        time.sleep(1)
    return False


def rows_for(camera_id: int):
    with SessionLocal() as s:
        return s.execute(text(
            "select frame_index, timestamp_s, admitted, frame_path from segments "
            "where camera_id = :c order by timestamp_s"), {"c": camera_id}).all()


def camera_status(c, camera_id: int) -> str:
    return next(x["status"] for x in c.get("/cameras").json() if x["id"] == camera_id)


def wait_status(c, camera_id: int, wanted: str, timeout_s: float) -> float | None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if camera_status(c, camera_id) == wanted:
            return time.time() - t0
        time.sleep(0.5)
    return None


def new_camera(c, label: str) -> int:
    r = c.post("/cameras", json={"name": f"{PREFIX}{label}", "rtsp_url": f"rtsp://mediamtx:8554/{ARGS.camera}",
                                 "location": "sim", "group": "sim", "domain": "surveillance"})
    return r.json()["id"]


def start_and_settle(c, camera_id: int, seconds: float) -> bool:
    r = c.post(f"/cameras/{camera_id}/start")
    if r.status_code != 200:
        print(f"    start failed: {r.status_code} {r.text[:150]}")
        return False
    time.sleep(seconds)
    return True


def sessions_of(rows):
    """Split a camera's rows into capture sessions: a frame index that goes back down
    is a new session (a restarted worker counts from zero again)."""
    out, cur, last = [], [], -1
    for r in rows:
        if r.frame_index <= last and cur:
            out.append(cur)
            cur = []
        cur.append(r)
        last = r.frame_index
    if cur:
        out.append(cur)
    return out


def analyse(rows, disk: set[str]) -> dict:
    """What a capture's stored rows say about loss, given the files on disk."""
    row_paths = {r.frame_path for r in rows if r.frame_path}
    gaps = []
    for sess in sessions_of(rows):
        idx = [r.frame_index for r in sess]
        gaps.append((idx[0], idx[-1], sorted(set(range(idx[0], idx[-1] + 1)) - set(idx))))
    return {"rows_without_file": row_paths - disk, "files_without_row": disk - row_paths, "sessions": gaps}


def selftest() -> None:
    """The loss detector must be able to fail: feed it a loss and see it say so."""
    from types import SimpleNamespace as R

    def row(i, path=True):
        return R(frame_index=i, timestamp_s=float(i), admitted=True, frame_path=f"/f/{i}.jpg" if path else None)

    good = [row(i) for i in range(10)] + [row(i) for i in range(4)]  # a session of 10, then a restarted one of 4
    disk = {f"/f/{i}.jpg" for i in range(10)}
    ok = analyse(good, disk)
    assert [(a, b, g) for a, b, g in ok["sessions"]] == [(0, 9, []), (0, 3, [])], ok
    lost_row = analyse([r for r in good if r.frame_index != 5 or r.timestamp_s != 5.0], disk)
    assert lost_row["sessions"][0][2] == [5] and lost_row["files_without_row"] == {"/f/5.jpg"}, lost_row
    lost_file = analyse(good, disk - {"/f/2.jpg"})
    assert lost_file["rows_without_file"] == {"/f/2.jpg"}, lost_file
    print("selftest: the detector flags a missing row, a missing file, and keeps restarted sessions apart")


def files_on_disk(camera_id: int) -> set[str]:
    out = dc("exec", "-T", "ingestion", "sh", "-c", f"find /data/frames/camera-{camera_id} -name '*.jpg' 2>/dev/null")
    return {ln.strip() for ln in out.stdout.splitlines() if ln.strip()}


selftest()
with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()
camera_ids: list[int] = []
video_ids: list[int] = []
c = None
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=120)
    print(f"stack: {dc('ps', '--format', '{{.Service}}={{.Status}}').stdout.split()}\n")

    # ---------------------------------------------------------------- A, B, C
    if ONLY & {"A", "B", "C"}:
        clip = SCRATCH / "still-then-moves.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=15:d=6",
            "-f", "lavfi", "-i", "testsrc2=s=320x240:r=15:d=6",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p", "-c:v", "libx264", str(clip)], check=True)
        with open(clip, "rb") as fh:
            up = c.post("/videos/upload", files={"file": (f"{PREFIX}still-then-moves.mp4", fh, "video/mp4")}).json()
        vid = up["id"]
        video_ids.append(vid)
        assert c.post(f"/videos/{vid}/extract").status_code == 202
        while c.get(f"/videos/{vid}").json()["status"] == "extracting":
            time.sleep(0.3)
        print("A. a recording that is still (6 s) and then moves (6 s), default gate parameters")
        with SessionLocal() as s:
            rows = s.execute(text(
                "select timestamp_s, admitted, admission_reason::text as reason from segments where video_id = :v order by frame_index"),
                {"v": vid}).all()
        still = [r for r in rows if r.timestamp_s < 6.0]
        moving = [r for r in rows if r.timestamp_s >= 6.0]
        still_motion = sum(1 for r in still if r.admitted and r.reason == "motion")
        still_heartbeat = sum(1 for r in still if r.admitted and r.reason == "heartbeat")
        moving_admitted = sum(1 for r in moving if r.admitted)
        print(f"    still part: {len(still)} frames, {still_motion} admitted by motion, {still_heartbeat} by the heartbeat; "
              f"moving part: {len(moving)} frames, {moving_admitted} admitted")
        check("A. no still frame is admitted for motion (only the heartbeat)", still_motion == 0)
        check("A. most still frames are discarded", len(still) > 0 and (len(still) - still_motion - still_heartbeat) / len(still) > 0.8,
              f"{len(still) - still_motion - still_heartbeat} of {len(still)} discarded")
        # the first 1 s of the video has no motion score (2 x stride warm-up), so judge the rest
        scored_moving = [r for r in moving if r.timestamp_s >= 6.0]
        check("A. moving frames are admitted", moving_admitted / max(1, len(scored_moving)) > 0.8,
              f"{moving_admitted} of {len(scored_moving)}")

        if "B" in ONLY:
            print("\nB. moving the threshold changes the counts (re-gating from stored frames)")
            counts = {}
            for thr in (5, 25, 100, 200):
                res = c.post(f"/videos/{vid}/gate", json={"cell_threshold": float(thr)})
                counts[thr] = res.json()["admitted"] if res.status_code == 200 else None
            print(f"    admitted at cell threshold 5 / 25 / 100 / 200: {counts}")
            vals = [counts[t] for t in (5, 25, 100, 200)]
            check("B. the counts change with the threshold", None not in vals and len(set(vals)) >= 2, str(vals))
            check("B. a higher threshold never admits more", None not in vals and all(a >= b for a, b in pairwise(vals)))
            c.post(f"/videos/{vid}/gate", json={})  # back to the defaults

        if "C" in ONLY:
            print("\nC. thumbnails carry the moment to seek to")
            frames = c.get(f"/videos/{vid}/frames", params={"limit": 200, "admitted": "true"}).json()
            check("C. admitted frames are listed with a timestamp", len(frames) > 0 and all("timestamp_s" in f for f in frames), f"{len(frames)} frames")
            if frames:
                pick = max(frames, key=lambda f: f["timestamp_s"])
                thumb = httpx.get(NGINX + pick["thumb_url"], verify=False)
                check("C. a thumbnail is served as an image", thumb.status_code == 200 and thumb.headers["content-type"].startswith("image/"),
                      f"{thumb.status_code} {thumb.headers.get('content-type')}")
                check("C. the last thumbnail's moment is inside the recording", 6.0 <= pick["timestamp_s"] <= up["duration_s"] + 0.5,
                      f"{pick['timestamp_s']:.2f} s of {up['duration_s']:.1f} s")
            play = httpx.get(NGINX + c.get(f"/videos/{vid}").json()["playback_url"], headers={"Range": "bytes=0-99"}, verify=False)
            check("C. the playback stream answers a range request (what seeking needs)", play.status_code == 206, f"{play.status_code}")

    # ------------------------------------------------------------------ D, E
    if ONLY & {"D", "E"}:
        print("\nD. a camera started against the simulator")
        cam = new_camera(c, "live")
        camera_ids.append(cam)
        check("D. the camera starts", start_and_settle(c, cam, 3))
        counts = []
        for _ in range(4):
            time.sleep(6)  # the worker reports its totals every 5 s, so poll slower than that
            counts.append(c.get(f"/cameras/{cam}/stats").json()["captured"])
        n_rows = len(rows_for(cam))
        print(f"    captured counter every 6 s: {counts}; rows stored: {n_rows}")
        check("D. the counters climb continuously", all(b > a for a, b in pairwise(counts)), str(counts))
        check("D. frames are stored", n_rows > 0, f"{n_rows} rows")
        check("D. the camera reads connected", camera_status(c, cam) == "connected")

        if "E" in ONLY:
            print("\nE. kill the simulator, then bring it back")
            dc("stop", "mediamtx")
            t_down = wait_status(c, cam, "unreachable", 60)
            check("E. the status flips to unreachable", t_down is not None, f"after {t_down:.1f} s" if t_down is not None else "did not within 60 s")
            before = c.get(f"/cameras/{cam}/stats").json()["captured"]
            dc("start", "mediamtx")
            t_up = wait_status(c, cam, "connected", 120)
            check("E. it recovers on its own (nobody touched the camera)", t_up is not None, f"after {t_up:.1f} s" if t_up is not None else "did not within 120 s")
            time.sleep(6)
            after = c.get(f"/cameras/{cam}/stats").json()["captured"]
            check("E. frames flow again", after > before, f"captured {before} -> {after}")
        c.post(f"/cameras/{cam}/stop")

    # -------------------------------------------------------------------- F
    if "F" in ONLY:
        def scenario(label: str, action, *, worker_dies: bool):
            print(f"\nF. restart mid-capture: {label}")
            cam = new_camera(c, f"restart-{label.split()[0]}")
            camera_ids.append(cam)
            if not start_and_settle(c, cam, 14):
                check(f"F/{label}. capture starts", False)
                return
            stored_before = len(rows_for(cam))
            print(f"    before the action: {stored_before} rows stored")
            action()
            time.sleep(3)
            drained = wait_drained()
            time.sleep(3)
            check(f"F/{label}. the queue drains afterwards", drained)
            if not worker_dies:
                # still capturing: prove it kept producing, then stop it and let the
                # queue drain so the files and rows can be compared without a race
                mid = len(rows_for(cam))
                time.sleep(6)
                check(f"F/{label}. the capture was never interrupted and went on producing", len(rows_for(cam)) > mid,
                      f"{mid} -> {len(rows_for(cam))} rows")
                c.post(f"/cameras/{cam}/stop")
                time.sleep(4)
                wait_drained()
                time.sleep(3)
            rows = rows_for(cam)
            disk = files_on_disk(cam)
            found = analyse(rows, disk)
            check(f"F/{label}. rows stored before the action are still there", len(rows) >= stored_before, f"{stored_before} -> {len(rows)}")
            check(f"F/{label}. every stored frame's file exists (no row without its file)", not found["rows_without_file"],
                  f"{len(found['rows_without_file'])} rows without a file")
            for i, (first, last, gaps) in enumerate(found["sessions"]):
                check(f"F/{label}. session {i + 1}: frame indexes {first}..{last} have no gap", not gaps,
                      f"missing {gaps[:8]}" if gaps else "")
            unconfirmed = found["files_without_row"]
            print(f"    files on disk without a row (written, never confirmed by the broker): {len(unconfirmed)}")
            check(f"F/{label}. at most a handful of frames were in flight", len(unconfirmed) <= (12 if worker_dies else 0), f"{len(unconfirmed)} files")
            if worker_dies:
                snap = json.loads(dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c",
                                     "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())").stdout or "[]")
                print(f"    camera status now: {camera_status(c, cam)}; workers in ingestion: {[w['camera_id'] for w in snap]}")
                check(f"F/{label}. the restarted worker did not resume by itself (known)", cam not in [w["camera_id"] for w in snap],
                      "capture has to be started again")
                again = c.post(f"/cameras/{cam}/start")
                check(f"F/{label}. capture can be started again", again.status_code == 200, f"{again.status_code}")
                time.sleep(8)
                more = rows_for(cam)
                check(f"F/{label}. new frames arrive as a new session and the old ones remain",
                      len(sessions_of(more)) == len(found["sessions"]) + 1 and len(more) > len(rows), f"{len(rows)} -> {len(more)} rows")
            c.post(f"/cameras/{cam}/stop")
            time.sleep(4)

        scenario("graceful (docker compose restart ingestion)", lambda: (dc("restart", "ingestion"), ingestion_up()), worker_dies=True)
        scenario("hard (kill -9 the ingestion container)", lambda: (dc("kill", "ingestion"), dc("up", "-d", "ingestion"), ingestion_up()), worker_dies=True)

        def stop_consumer_a_while():
            dc("stop", "consumer")
            time.sleep(15)
            print(f"    queue depth while the consumer is down: {queue_depth(SETTINGS.segment_queue)}")
            dc("start", "consumer")

        scenario("consumer (stopped 15 s and started again)", stop_consumer_a_while, worker_dies=False)

        def kill_consumer_a_while():
            dc("kill", "consumer")
            time.sleep(15)
            print(f"    queue depth while the consumer is dead: {queue_depth(SETTINGS.segment_queue)}")
            dc("start", "consumer")

        scenario("consumer killed (kill -9 for 15 s, then started)", kill_consumer_a_while, worker_dies=False)

    print("\n=== summary")
    for label, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
finally:
    dc("start", "consumer")
    dc("start", "mediamtx")
    dc("up", "-d", "ingestion")
    if c is not None:
        for cid in camera_ids:
            try:
                c.post(f"/cameras/{cid}/stop")
            except Exception:  # noqa: BLE001, S110 - cleanup must carry on
                pass
        for vid in video_ids:
            try:
                c.delete(f"/videos/{vid}")
            except Exception:  # noqa: BLE001, S110
                pass
    if camera_ids:
        wait_drained(300)
        time.sleep(3)
        with SessionLocal() as s:
            s.query(Segment).filter(Segment.camera_id.in_(camera_ids)).delete(synchronize_session=False)
            s.query(CameraStats).filter(CameraStats.camera_id.in_(camera_ids)).delete(synchronize_session=False)
            s.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
            s.commit()
        dirs = " ".join(f"/data/frames/camera-{cid} /data/thumbs/camera-{cid}" for cid in camera_ids)
        dc("exec", "-T", "ingestion", "sh", "-c", f"rm -rf {dirs}")
    with SessionLocal() as s:
        s.query(Video).filter(Video.filename.like(f"{PREFIX}%")).delete(synchronize_session=False)
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()
    print("cleaned up")
