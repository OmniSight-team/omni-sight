"""The definition of done for slices 3 and 4, run against the live stack (OMNI-319);
check F brought up to date for slice 5's live pipeline (OMNI-601).

Checks, through the real API, database, broker and containers:

  A  a recording that is still and then moves: early frames discarded (heartbeat only),
     moving frames admitted
  B  moving the threshold changes the counts (re-gating the stored frames)
  C  a thumbnail carries the moment to seek to, and the thumbnail and the playback
     stream are served (the click itself is a browser check, not done here)
  D  a camera started against the simulator: frames arrive continuously, counters climb
  E  the simulator killed: the camera goes unreachable, then recovers on its own
  F  a failure mid-capture, four ways, and nothing already accepted is lost:
       graceful  `docker compose restart ingestion`
       hard      `docker compose kill ingestion` (SIGKILL, no shutdown code runs)
       consumer  `docker compose stop consumer-live` for 15 s, then start (the queue holds the backlog)
       killed    `docker compose kill consumer-live` for 15 s, then start

"Accepted" means the broker confirmed the publish. Since OMNI-501 a live camera stores
admitted frames only, while its frame index counts every captured frame, so gaps in a
session's indexes are normal and say nothing about loss. Loss is, instead:
  - a row whose file is missing, or
  - fewer stored rows than the worker said it had admitted: per session, against the
    highest `camera_stats` report seen while it ran, and per camera, against the
    lifetime `admitted` counters. The worker counts a frame as admitted after writing
    it to disk, publishes it (confirmed) before taking the next frame, and reports
    between frames, so every report's count was already confirmed by the broker.
A file without a row is a frame written but never confirmed (allowed only for a killed
worker's last moments). Since OMNI-504 the restarted worker resumes by itself. Since
OMNI-502 live frames go to their own queue and consumer (`consumer-live`), so the check
waits for the file queue, the live queue and the camera queue (the stats) to drain.

Run from the repo root, in the background (it takes several minutes):

  PYTHONPATH=services/query nohup uv run --package omnisight-query \\
      python scripts/verify_definition_of_done.py > /tmp/dod319.txt 2>&1 &

`--only A,B,C` (letters) runs some of them. Everything it creates is removed at the end.
"""

import argparse
import os
import subprocess
import tempfile
import threading
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


DRAINED_QUEUES = (SETTINGS.segment_queue, SETTINGS.live_segment_queue, SETTINGS.camera_event_queue)


def wait_drained(timeout_s: float = 180) -> bool:
    deadline = time.time() + timeout_s
    calm = 0
    while time.time() < deadline:
        try:
            calm = calm + 1 if all(queue_depth(q) == 0 for q in DRAINED_QUEUES) else 0
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


class StatsWatch:
    """Reads a camera's `camera_stats` row every half second while a scenario runs and
    keeps the highest `admitted` each session (worker) reported. Every report counts
    frames the broker had already confirmed (see the docstring), so it is a floor for
    that session's stored rows. Sessions are kept in the order they appeared."""

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.by_session: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(0.5)

    def poll(self) -> None:
        with SessionLocal() as s:
            r = s.execute(text(
                "select session_id, session_admitted_motion + session_admitted_heartbeat as admitted "
                "from camera_stats where camera_id = :c"), {"c": self.camera_id}).first()
        if r is not None and r.session_id:
            self.by_session[r.session_id] = max(self.by_session.get(r.session_id, 0), r.admitted)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self.poll()

    def counts(self) -> list[int]:
        return list(self.by_session.values())


def lifetime_admitted(camera_id: int) -> int:
    with SessionLocal() as s:
        return s.execute(text(
            "select coalesce(sum(admitted_motion + admitted_heartbeat), 0) from camera_stats where camera_id = :c"),
            {"c": camera_id}).scalar_one()


def analyse(rows, disk: set[str], session_counts: list[int], lifetime: int) -> dict:
    """What a live capture's stored rows say about loss, given the files on disk and
    the admitted counts the worker reported (per session, and the camera's lifetime
    total). Gaps in the frame indexes are not looked at: they are normal (OMNI-501)."""
    row_paths = {r.frame_path for r in rows if r.frame_path}
    sessions = []
    for i, sess in enumerate(sessions_of(rows)):
        counted = session_counts[i] if i < len(session_counts) else None
        sessions.append({"first": sess[0].frame_index, "last": sess[-1].frame_index, "rows": len(sess),
                         "admitted": counted, "short": max(0, (counted or 0) - len(sess))})
    # a session the worker reported but none of whose rows were stored is short by all of it
    for counted in session_counts[len(sessions):]:
        sessions.append({"first": None, "last": None, "rows": 0, "admitted": counted, "short": counted})
    return {"rows_without_file": row_paths - disk, "files_without_row": disk - row_paths, "sessions": sessions,
            "rows": len(rows), "lifetime_admitted": lifetime, "lifetime_short": max(0, lifetime - len(rows))}


def selftest() -> None:
    """The loss detector must be able to fail: feed it a loss and see it say so, and
    feed it a normal live capture (gaps in the indexes) and see it stay quiet."""
    from types import SimpleNamespace as R

    def row(i, session):
        return R(frame_index=i, timestamp_s=float(session * 100 + i), admitted=True, frame_path=f"/f/{session}-{i}.jpg")

    # live: admitted frames only, so the indexes have gaps; a session, then a restarted one
    good = [row(i, 0) for i in (0, 3, 4, 9, 15, 16)] + [row(i, 1) for i in (0, 2, 7)]
    disk = {r.frame_path for r in good}
    ok = analyse(good, disk, [6, 3], 9)
    assert [(x["first"], x["last"], x["rows"], x["short"]) for x in ok["sessions"]] == [(0, 16, 6, 0), (0, 7, 3, 0)], ok
    assert not ok["rows_without_file"] and not ok["files_without_row"] and ok["lifetime_short"] == 0, ok
    # a killed worker's last report is below what it stored: not a loss
    assert analyse(good, disk, [4, 3], 7)["lifetime_short"] == 0
    lost_row = analyse([r for r in good if r.frame_path != "/f/0-9.jpg"], disk, [6, 3], 9)
    assert lost_row["sessions"][0]["short"] == 1 and lost_row["lifetime_short"] == 1, lost_row
    assert lost_row["files_without_row"] == {"/f/0-9.jpg"}, lost_row
    lost_file = analyse(good, disk - {"/f/1-2.jpg"}, [6, 3], 9)
    assert lost_file["rows_without_file"] == {"/f/1-2.jpg"}, lost_file
    short = analyse(good, disk, [6, 5], 11)
    assert short["sessions"][1]["short"] == 2 and short["lifetime_short"] == 2, short
    print("selftest: the detector flags a missing row, a missing file and a short count, "
          "and does not flag the normal gaps of a live capture")


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
            print(f"\nF. failure mid-capture: {label}")
            cam = new_camera(c, f"restart-{label.split()[0]}")
            camera_ids.append(cam)
            with StatsWatch(cam) as watch:
                if not start_and_settle(c, cam, 14):
                    check(f"F/{label}. capture starts", False)
                    return
                stored_before = len(rows_for(cam))
                print(f"    before the action: {stored_before} rows stored")
                action()
                time.sleep(3)
                drained = wait_drained()
                time.sleep(3)
                check(f"F/{label}. the queues drain afterwards", drained)
                if worker_dies:
                    # OMNI-504: query starts the camera's worker again by itself
                    deadline = time.time() + 60
                    while time.time() < deadline and len(sessions_of(rows_for(cam))) < 2:
                        time.sleep(1)
                    n_sessions = len(sessions_of(rows_for(cam)))
                    check(f"F/{label}. capture resumed by itself in a new session (OMNI-504)", n_sessions >= 2,
                          f"{n_sessions} sessions")
                # capturing still (or again): prove it goes on producing, then stop it and let
                # the queues drain so files, rows and counters are compared without a race
                mid = len(rows_for(cam))
                time.sleep(6)
                check(f"F/{label}. capture goes on producing after the failure", len(rows_for(cam)) > mid,
                      f"{mid} -> {len(rows_for(cam))} rows")
                c.post(f"/cameras/{cam}/stop")
                time.sleep(4)
                wait_drained()
                time.sleep(3)
            rows = rows_for(cam)
            disk = files_on_disk(cam)
            found = analyse(rows, disk, watch.counts(), lifetime_admitted(cam))
            check(f"F/{label}. rows stored before the action are still there", len(rows) >= stored_before, f"{stored_before} -> {len(rows)}")
            check(f"F/{label}. every stored frame's file exists (no row without its file)", not found["rows_without_file"],
                  f"{len(found['rows_without_file'])} rows without a file")
            for i, sess in enumerate(found["sessions"]):
                check(f"F/{label}. session {i + 1}: stored rows not short of the admitted counter",
                      sess["admitted"] is not None and sess["short"] == 0,
                      f"{sess['rows']} rows, worker reported {sess['admitted']} admitted, indexes {sess['first']}..{sess['last']}")
            check(f"F/{label}. camera total: stored rows not short of the lifetime admitted counter", found["lifetime_short"] == 0,
                  f"{found['rows']} rows, {found['lifetime_admitted']} admitted")
            unconfirmed = found["files_without_row"]
            print(f"    files on disk without a row (written, never confirmed by the broker): {len(unconfirmed)}")
            check(f"F/{label}. at most a handful of frames were in flight", len(unconfirmed) <= (12 if worker_dies else 0), f"{len(unconfirmed)} files")
            with SessionLocal() as s:
                st = s.execute(text("select captured, dropped, gated, discarded from camera_stats where camera_id = :c"),
                               {"c": cam}).first()
            print(f"    camera_stats: captured {st.captured}, dropped {st.dropped}, gated {st.gated}, "
                  f"admitted {found['lifetime_admitted']}, discarded {st.discarded}; per session seen: {watch.counts()}")

        scenario("graceful (docker compose restart ingestion)", lambda: (dc("restart", "ingestion"), ingestion_up()), worker_dies=True)
        scenario("hard (kill -9 the ingestion container)", lambda: (dc("kill", "ingestion"), dc("up", "-d", "ingestion"), ingestion_up()), worker_dies=True)

        # OMNI-502: live frames are stored by `consumer-live`, from a queue of their own
        def stop_consumer_a_while():
            dc("stop", "consumer-live")
            time.sleep(15)
            print(f"    live queue depth while consumer-live is down: {queue_depth(SETTINGS.live_segment_queue)}")
            dc("start", "consumer-live")

        scenario("consumer-live (stopped 15 s and started again)", stop_consumer_a_while, worker_dies=False)

        def kill_consumer_a_while():
            dc("kill", "consumer-live")
            time.sleep(15)
            print(f"    live queue depth while consumer-live is dead: {queue_depth(SETTINGS.live_segment_queue)}")
            dc("start", "consumer-live")

        scenario("consumer-live killed (kill -9 for 15 s, then started)", kill_consumer_a_while, worker_dies=False)

    print("\n=== summary")
    for label, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
finally:
    dc("start", "consumer")
    dc("start", "consumer-live")
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
