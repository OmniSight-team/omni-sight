"""OMNI-311: the segment consumer — acknowledge after commit, never lose a
frame, never store one twice.

Needs Postgres (with `alembic upgrade head`) and RabbitMQ (`docker compose up
-d rabbitmq`). No mocks of either: the messages go through the real broker and
the rows land in the real database. Each test uses a queue of its own, so none
of this competes with the running consumer for the real one.

"Killing the consumer" is simulated by making it raise part-way through a
delivery and then closing its connection without acknowledging anything, which
is what the broker sees when the process dies. The same thing was also done for
real, with `docker compose kill consumer`, against the running stack
(docs/context/week-03-04.md).
"""

import time
import uuid
from datetime import UTC, datetime

import pika
import pytest
from app import consumer as consumer_module
from app.consumer import (
    MalformedMessage,
    Outcome,
    apply_camera_event,
    apply_camera_message,
    apply_camera_stats,
    store_segment,
)
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, Video
from app.settings import settings
from omnisight_common import (
    CameraEvent,
    CameraStatsReport,
    CameraStatus,
    Domain,
    SegmentMessage,
    VideoSource,
    VideoStatus,
    connection_parameters,
    dead_letter_queue,
    declare_segment_queue,
)

NAME_PREFIX = "omni311-"
RUN = "run-A"
PARAMS = connection_parameters(settings)


@pytest.fixture
def queue(monkeypatch):
    name = f"omni311-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "segment_queue", name)
    yield name
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.queue_delete(name)
        channel.queue_delete(dead_letter_queue(name))


@pytest.fixture
def live_queue(monkeypatch):
    name = f"omni502-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "live_segment_queue", name)
    yield name
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.queue_delete(name)
        channel.queue_delete(dead_letter_queue(name))


@pytest.fixture
def event_queue(monkeypatch):
    name = f"omni313-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "camera_event_queue", name)
    yield name
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.queue_delete(name)
        channel.queue_delete(dead_letter_queue(name))


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(
            synchronize_session=False
        )
        camera_ids = [c.id for c in session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(Segment.camera_id.in_(camera_ids)).delete(
            synchronize_session=False
        )
        session.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
        session.commit()


def _video(status=VideoStatus.EXTRACTING, extraction_id=RUN) -> int:
    with SessionLocal() as session:
        video = Video(
            filename=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}.mp4",
            path="/nonexistent.mp4",
            source=VideoSource.UPLOAD,
            size_bytes=1,
            status=status,
            extraction_id=extraction_id,
        )
        session.add(video)
        session.commit()
        return video.id


def _message(video_id, index, *, extraction_id=RUN, camera_id=None) -> SegmentMessage:
    return SegmentMessage(
        video_id=video_id,
        camera_id=camera_id,
        frame_index=index,
        timestamp_s=index / 30,
        frame_path=None,
        thumb_path=None,
        motion_score=2.0,
        admitted=False,
        source_type="upload" if camera_id is None else "camera",
        extraction_id=extraction_id,
    )


def _body(video_id, index, **kwargs) -> bytes:
    return _message(video_id, index, **kwargs).model_dump_json().encode()


def _rows(video_id) -> list[int]:
    with SessionLocal() as session:
        return sorted(
            index
            for (index,) in session.query(Segment.frame_index).filter_by(video_id=video_id)
        )


def _publish(queue_name, bodies):
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.confirm_delivery()
        declare_segment_queue(channel, queue_name)
        for body in bodies:
            channel.basic_publish(
                "",
                queue_name,
                body,
                pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent),
                mandatory=True,
            )


def _ready(queue_name) -> int:
    """Messages waiting in the queue (delivered-but-unacknowledged ones are not
    counted, so this drops the instant a consumer is handed a message)."""
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        return channel.queue_declare(queue_name, passive=True).method.message_count


def _run_consumer(callback, *, seconds=3.0, until=None, on_event=None, queue=None):
    """Connect the way the real consumer does and process deliveries for a
    while, then drop the connection *without* acknowledging anything still
    open. Returns the exception the callback raised, if any — a consumer that
    dies mid-delivery."""
    connection = pika.BlockingConnection(PARAMS)
    error = None
    try:
        channel = connection.channel()
        consumer_module.start(channel, on_message=callback, on_event=on_event, queue=queue)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            connection.process_data_events(time_limit=0.2)
            if until is not None and until():
                break
    except Exception as exc:  # noqa: BLE001 - the "crash" under test
        error = exc
    finally:
        connection.close()
    return error


# --- store_segment: what one message does to the database -------------------


def test_a_message_for_the_current_extraction_becomes_a_row():
    video_id = _video()

    assert store_segment(_body(video_id, 4)) is Outcome.STORED

    assert _rows(video_id) == [4]


def test_the_same_message_delivered_twice_is_one_row():
    """A consumer that dies after committing but before acknowledging gets the
    message again — the database, not luck, makes that harmless."""
    video_id = _video()

    assert store_segment(_body(video_id, 4)) is Outcome.STORED
    assert store_segment(_body(video_id, 4)) is Outcome.DUPLICATE

    assert _rows(video_id) == [4]


def test_a_frame_from_an_older_extraction_is_dropped():
    video_id = _video(extraction_id="the-current-run")

    assert store_segment(_body(video_id, 0, extraction_id="an-older-run")) is Outcome.STALE

    assert _rows(video_id) == []


@pytest.mark.parametrize("status", [VideoStatus.READY, VideoStatus.FAILED])
def test_a_frame_for_a_video_that_is_not_extracting_is_dropped(status):
    video_id = _video(status=status)

    assert store_segment(_body(video_id, 0)) is Outcome.STALE

    assert _rows(video_id) == []


def test_a_frame_for_a_video_that_no_longer_exists_is_dropped():
    assert store_segment(_body(2_000_000_000, 0)) is Outcome.STALE


def test_a_message_that_cannot_be_parsed_is_reported_not_stored():
    with pytest.raises(MalformedMessage):
        store_segment(b"this is not a segment")


def _camera() -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}cam-{uuid.uuid4().hex[:6]}",
            rtsp_url="rtsp://example.invalid/x",
            location="test",
            group_name="test",
            domain=Domain.SURVEILLANCE,
            status=CameraStatus.REGISTERED,
        )
        session.add(camera)
        session.commit()
        return camera.id


def _live_body(camera_id, timestamp_s, frame_index=0) -> bytes:
    return (
        SegmentMessage(
            video_id=None,
            camera_id=camera_id,
            frame_index=frame_index,
            timestamp_s=timestamp_s,
            frame_path=None,
            thumb_path=None,
            motion_score=2.0,
            admitted=False,
            source_type="camera",
        )
        .model_dump_json()
        .encode()
    )


def _camera_rows(camera_id) -> list[float]:
    with SessionLocal() as session:
        return sorted(
            t for (t,) in session.query(Segment.timestamp_s).filter_by(camera_id=camera_id)
        )


def test_a_camera_frame_is_stored_without_a_video():
    camera_id = _camera()

    assert store_segment(_live_body(camera_id, 1_790_000_000.25)) is Outcome.STORED

    with SessionLocal() as session:
        row = session.query(Segment).filter_by(camera_id=camera_id).one()
        assert row.video_id is None and row.source_type.value == "camera"


def test_a_live_frame_delivered_twice_is_one_row():
    """The same guarantee as for a file's frames, for a frame with no video: a
    consumer killed between committing and acknowledging gets it again."""
    camera_id = _camera()
    body = _live_body(camera_id, 1_790_000_000.25)

    assert store_segment(body) is Outcome.STORED
    assert store_segment(body) is Outcome.DUPLICATE

    assert _camera_rows(camera_id) == [1_790_000_000.25]


def test_different_moments_of_the_same_camera_are_different_rows():
    camera_id = _camera()

    for t in (1_790_000_000.25, 1_790_000_000.45, 1_790_000_000.65):
        assert store_segment(_live_body(camera_id, t)) is Outcome.STORED

    assert len(_camera_rows(camera_id)) == 3


def test_two_cameras_may_have_a_frame_at_the_same_moment():
    first, second = _camera(), _camera()

    assert store_segment(_live_body(first, 1_790_000_000.25)) is Outcome.STORED
    assert store_segment(_live_body(second, 1_790_000_000.25)) is Outcome.STORED


def test_a_live_frame_for_a_camera_that_no_longer_exists_is_dropped_not_retried_for_ever():
    """Without this the foreign key fails, the consumer drops its connection, and
    the same message fails the same way on every redelivery."""
    assert store_segment(_live_body(2_000_000_000, 1_790_000_000.25)) is Outcome.STALE


def test_a_message_with_neither_a_video_nor_a_camera_is_malformed():
    with pytest.raises(MalformedMessage):
        store_segment(_live_body(None, 1_790_000_000.25))


# --- camera status events and last_seen_at (OMNI-313) -----------------------------


def _event(camera_id, status, at=1_790_000_100.0) -> bytes:
    return CameraEvent(camera_id=camera_id, status=status, at=at).model_dump_json().encode()


def _camera_row(camera_id) -> Camera:
    with SessionLocal() as session:
        return session.get(Camera, camera_id)


def _set_camera_status(camera_id, status):
    with SessionLocal() as session:
        session.get(Camera, camera_id).status = status
        session.commit()


def test_an_unreachable_event_flips_the_camera_to_unreachable():
    camera_id = _camera()
    _set_camera_status(camera_id, CameraStatus.CONNECTED)

    assert apply_camera_event(_event(camera_id, "unreachable")) is Outcome.STORED

    assert _camera_row(camera_id).status == CameraStatus.UNREACHABLE


def test_a_connected_event_flips_it_back_and_records_when_it_was_seen():
    camera_id = _camera()
    _set_camera_status(camera_id, CameraStatus.UNREACHABLE)

    apply_camera_event(_event(camera_id, "connected", at=1_790_000_100.0))

    row = _camera_row(camera_id)
    assert row.status == CameraStatus.CONNECTED
    assert row.last_seen_at == datetime.fromtimestamp(1_790_000_100.0, UTC)


def test_a_disabled_camera_stays_disabled_whatever_its_stream_does():
    camera_id = _camera()
    _set_camera_status(camera_id, CameraStatus.DISABLED)

    assert apply_camera_event(_event(camera_id, "connected")) is Outcome.STALE

    assert _camera_row(camera_id).status == CameraStatus.DISABLED


def test_an_event_for_a_camera_that_no_longer_exists_is_dropped():
    assert apply_camera_event(_event(2_000_000_000, "unreachable")) is Outcome.STALE


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"camera_id": 1, "status": "registered", "at": 1.0}',
        b'{"camera_id": 1, "status": "disabled", "at": 1.0}',
    ],
)
def test_an_event_that_says_anything_but_connected_or_unreachable_is_malformed(body):
    with pytest.raises(MalformedMessage):
        apply_camera_event(body)


def test_an_event_is_acknowledged_only_after_the_camera_is_updated(queue, event_queue, monkeypatch):
    camera_id = _camera()
    _set_camera_status(camera_id, CameraStatus.CONNECTED)
    _publish(event_queue, [_event(camera_id, "unreachable")])

    def database_down(_body):
        raise RuntimeError("database is down")

    monkeypatch.setattr(consumer_module, "apply_camera_event", database_down)
    error = _run_consumer(
        consumer_module._on_message, on_event=consumer_module._on_event, seconds=2.0
    )

    assert isinstance(error, RuntimeError)
    assert _ready(event_queue) == 1  # still queued: had it been acknowledged first, the change would be lost
    assert _camera_row(camera_id).status == CameraStatus.CONNECTED

    monkeypatch.setattr(consumer_module, "apply_camera_event", apply_camera_event)
    _run_consumer(
        consumer_module._on_message,
        on_event=consumer_module._on_event,
        until=lambda: _camera_row(camera_id).status == CameraStatus.UNREACHABLE,
    )

    assert _camera_row(camera_id).status == CameraStatus.UNREACHABLE
    time.sleep(0.5)
    assert _ready(event_queue) == 0


def test_an_unparseable_event_goes_to_its_dead_letter_queue(queue, event_queue):
    _publish(event_queue, [b"not json"])

    _run_consumer(
        consumer_module._on_message,
        on_event=consumer_module._on_event,
        until=lambda: _ready(event_queue) == 0,
    )
    time.sleep(0.5)

    assert _ready(event_queue) == 0
    assert _ready(dead_letter_queue(event_queue)) == 1


def test_a_stored_live_frame_records_when_its_camera_was_last_seen():
    camera_id = _camera()

    store_segment(_live_body(camera_id, 1_790_000_000.25))

    assert _camera_row(camera_id).last_seen_at == datetime.fromtimestamp(1_790_000_000.25, UTC)


def test_last_seen_is_not_rewritten_for_every_frame():
    camera_id = _camera()
    store_segment(_live_body(camera_id, 1_790_000_000.25))

    store_segment(_live_body(camera_id, 1_790_000_001.25))  # a second later: inside the interval
    assert _camera_row(camera_id).last_seen_at == datetime.fromtimestamp(1_790_000_000.25, UTC)

    store_segment(_live_body(camera_id, 1_790_000_006.5))  # six seconds later: past it
    assert _camera_row(camera_id).last_seen_at == datetime.fromtimestamp(1_790_000_006.5, UTC)


def test_a_late_frame_never_moves_last_seen_backwards():
    camera_id = _camera()
    store_segment(_live_body(camera_id, 1_790_000_100.0))

    store_segment(_live_body(camera_id, 1_790_000_000.0))  # older, arriving late

    assert _camera_row(camera_id).last_seen_at == datetime.fromtimestamp(1_790_000_100.0, UTC)


# --- camera stats reports (OMNI-314) ----------------------------------------------


def _report(camera_id, *, worker="worker-1", captured=0, dropped=0, at=1_790_000_100.0,
            started_at=1_790_000_000.0, fps=5.0, running=True, last_frame_at=None,
            motion=0, heartbeat=0, discarded=0) -> bytes:
    return CameraStatsReport(
        camera_id=camera_id, worker_id=worker, started_at=started_at, at=at,
        captured=captured, dropped=dropped, fps_effective=fps, running=running,
        last_frame_at=last_frame_at,
        gated=motion + heartbeat + discarded, admitted_motion=motion,
        admitted_heartbeat=heartbeat, discarded=discarded,
    ).model_dump_json().encode()


def _gate_counters(row) -> tuple[int, int, int, int]:
    return (row.gated, row.admitted_motion, row.admitted_heartbeat, row.discarded)


def _stats(camera_id) -> CameraStats:
    with SessionLocal() as session:
        return session.get(CameraStats, camera_id)


def test_a_first_report_becomes_the_cameras_totals():
    camera_id = _camera()

    assert apply_camera_stats(_report(camera_id, captured=100, dropped=3)) is Outcome.STORED

    row = _stats(camera_id)
    assert (row.captured, row.dropped) == (100, 3)
    assert row.session_id == "worker-1"


def test_a_later_report_adds_only_what_is_new():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, captured=100, dropped=3, at=1_790_000_100.0))

    apply_camera_stats(_report(camera_id, captured=150, dropped=5, at=1_790_000_105.0))

    row = _stats(camera_id)
    # The totals, not 250 and 8: a report carries running totals, not increments.
    assert (row.captured, row.dropped) == (150, 5)


def test_the_same_report_delivered_twice_counts_once():
    """A consumer killed between committing and acknowledging gets it again."""
    camera_id = _camera()
    body = _report(camera_id, captured=100, dropped=3)

    apply_camera_stats(body)
    apply_camera_stats(body)

    row = _stats(camera_id)
    assert (row.captured, row.dropped) == (100, 3)


def test_a_late_report_with_lower_totals_adds_nothing_and_takes_nothing_away():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, captured=150, dropped=5, at=1_790_000_105.0))

    apply_camera_stats(_report(camera_id, captured=100, dropped=3, at=1_790_000_100.0))

    row = _stats(camera_id)
    assert (row.captured, row.dropped) == (150, 5)


def test_a_new_capture_session_adds_to_the_lifetime_totals():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, worker="first", captured=100, dropped=3))

    apply_camera_stats(_report(camera_id, worker="second", captured=40, dropped=1))

    row = _stats(camera_id)
    assert (row.captured, row.dropped) == (140, 4)  # both sessions
    assert row.session_id == "second" and row.session_captured == 40


def test_the_gate_counters_are_folded_in_like_the_others():
    """OMNI-501: gated, admitted (motion and heartbeat) and discarded."""
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, captured=100, motion=10, heartbeat=5, discarded=85))

    later = _report(camera_id, captured=150, motion=18, heartbeat=7, discarded=125, at=1_790_000_105.0)
    apply_camera_stats(later)
    apply_camera_stats(later)  # delivered twice: counted once

    row = _stats(camera_id)
    # The totals, not the two reports added together.
    assert _gate_counters(row) == (150, 18, 7, 125)
    assert row.gated == row.admitted_motion + row.admitted_heartbeat + row.discarded
    assert row.captured == row.gated + row.dropped


def test_the_gate_counters_add_up_across_capture_sessions():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, worker="first", captured=100, motion=10, heartbeat=5, discarded=85))

    apply_camera_stats(_report(camera_id, worker="second", captured=40, motion=1, heartbeat=9, discarded=30))

    row = _stats(camera_id)
    assert _gate_counters(row) == (140, 11, 14, 115)
    assert row.session_gated == 40 and row.session_discarded == 30


def test_a_report_from_before_the_gate_counters_existed_still_applies():
    camera_id = _camera()
    old_style = (
        b'{"kind": "stats", "camera_id": %d, "worker_id": "old", "started_at": 1790000000.0, '
        b'"at": 1790000100.0, "captured": 50, "dropped": 2, "fps_effective": 4.0}' % camera_id
    )

    assert apply_camera_message(old_style) is Outcome.STORED

    row = _stats(camera_id)
    assert (row.captured, row.dropped) == (50, 2)
    assert _gate_counters(row) == (0, 0, 0, 0)


def test_a_running_report_records_the_rate_and_when_the_session_began():
    camera_id = _camera()

    apply_camera_stats(_report(camera_id, fps=4.2, started_at=1_790_000_000.0, at=1_790_000_100.0))

    row = _stats(camera_id)
    assert row.fps_effective == 4.2
    assert row.session_started_at == datetime.fromtimestamp(1_790_000_000.0, UTC)
    assert row.reported_at == datetime.fromtimestamp(1_790_000_100.0, UTC)


def test_a_final_report_marks_the_camera_as_not_running():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, captured=100, at=1_790_000_100.0))

    apply_camera_stats(_report(camera_id, captured=120, running=False, at=1_790_000_110.0))

    row = _stats(camera_id)
    assert row.session_started_at is None and row.fps_effective == 0.0
    assert row.captured == 120  # and its last totals still counted


def test_a_late_running_report_does_not_bring_a_stopped_camera_back():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, captured=120, running=False, at=1_790_000_110.0))

    apply_camera_stats(_report(camera_id, captured=100, running=True, at=1_790_000_100.0))  # older

    row = _stats(camera_id)
    assert row.session_started_at is None  # it is still stopped


def test_the_newest_frame_time_only_moves_forward():
    camera_id = _camera()
    apply_camera_stats(_report(camera_id, last_frame_at=1_790_000_100.0, at=1_790_000_105.0))

    apply_camera_stats(_report(camera_id, last_frame_at=1_790_000_050.0, at=1_790_000_106.0))

    assert _stats(camera_id).last_frame_at == datetime.fromtimestamp(1_790_000_100.0, UTC)


def test_a_report_for_a_camera_that_no_longer_exists_is_dropped():
    assert apply_camera_stats(_report(2_000_000_000, captured=5)) is Outcome.STALE


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"kind": "stats", "camera_id": 1}',  # missing everything else
        b'["a list"]',
        b'{"kind": "surprise", "camera_id": 1}',
    ],
)
def test_a_camera_message_that_makes_no_sense_is_malformed(body):
    with pytest.raises(MalformedMessage):
        apply_camera_message(body)


def test_the_camera_queue_still_carries_status_changes_as_before():
    camera_id = _camera()
    _set_camera_status(camera_id, CameraStatus.CONNECTED)
    old_style = b'{"camera_id": %d, "status": "unreachable", "at": 1790000100.0}' % camera_id  # no "kind"

    assert apply_camera_message(old_style) is Outcome.STORED

    assert _camera_row(camera_id).status == CameraStatus.UNREACHABLE


def test_a_report_on_the_queue_is_applied_and_acknowledged(queue, event_queue):
    camera_id = _camera()
    _publish(event_queue, [_report(camera_id, captured=77, dropped=2)])

    _run_consumer(
        consumer_module._on_message,
        on_event=consumer_module._on_event,
        until=lambda: _stats(camera_id) is not None and _stats(camera_id).captured == 77,
    )

    assert (_stats(camera_id).captured, _stats(camera_id).dropped) == (77, 2)
    time.sleep(0.5)
    assert _ready(event_queue) == 0


# --- the acknowledgement: after the commit, never before --------------------


def test_a_message_is_not_acknowledged_when_its_row_could_not_be_committed(queue, monkeypatch):
    video_id = _video()
    _publish(queue, [_body(video_id, 0)])

    def database_down(_body):
        raise RuntimeError("database is down")

    monkeypatch.setattr(consumer_module, "store_segment", database_down)
    error = _run_consumer(consumer_module._on_message)

    assert isinstance(error, RuntimeError)
    # The message is still there: had it been acknowledged first, it would be
    # gone and this frame would be lost.
    assert _ready(queue) == 1
    assert _rows(video_id) == []


def test_a_consumer_killed_after_committing_but_before_acknowledging_causes_no_duplicate(
    queue, monkeypatch
):
    video_id = _video()
    _publish(queue, [_body(video_id, 0)])

    def commit_then_die(body):
        outcome = store_segment(body)
        raise RuntimeError("killed between the commit and the acknowledgement")
        return outcome  # pragma: no cover

    monkeypatch.setattr(consumer_module, "store_segment", commit_then_die)
    assert isinstance(_run_consumer(consumer_module._on_message), RuntimeError)
    assert _rows(video_id) == [0]  # the row was committed...
    assert _ready(queue) == 1  # ...but the broker still holds the message

    monkeypatch.setattr(consumer_module, "store_segment", store_segment)
    _run_consumer(consumer_module._on_message, until=lambda: _ready(queue) == 0)

    assert _rows(video_id) == [0]  # redelivered, recognised, not stored twice
    assert _ready(queue) == 0  # and finally acknowledged


def test_kill_the_consumer_mid_run_and_nothing_is_lost_or_duplicated(queue, monkeypatch):
    """The ticket's acceptance test."""
    total = 60
    video_id = _video()
    _publish(queue, [_body(video_id, i) for i in range(total)])

    calls = {"count": 0}

    def dies_on_the_26th_message(body):
        calls["count"] += 1
        if calls["count"] == 26:
            # Killed part-way through handling a delivery, before its row is
            # committed. The real callback is the one running: if it had
            # acknowledged first, this frame would be gone for good.
            raise RuntimeError("killed mid-run")
        return store_segment(body)

    monkeypatch.setattr(consumer_module, "store_segment", dies_on_the_26th_message)
    assert isinstance(_run_consumer(consumer_module._on_message), RuntimeError)
    stored_before_the_kill = len(_rows(video_id))
    assert stored_before_the_kill == 25  # it really died part-way

    # A fresh consumer takes over and finishes.
    monkeypatch.setattr(consumer_module, "store_segment", store_segment)
    _run_consumer(consumer_module._on_message, seconds=15, until=lambda: len(_rows(video_id)) == total)

    assert _rows(video_id) == list(range(total))  # every frame, each exactly once
    time.sleep(0.5)
    assert _ready(queue) == 0


# --- prefetch and dead letters ----------------------------------------------


def test_prefetch_limits_how_many_messages_one_consumer_holds(queue, monkeypatch):
    monkeypatch.setattr(settings, "segment_prefetch", 3)
    video_id = _video()
    _publish(queue, [_body(video_id, i) for i in range(12)])
    held = []

    def hold_without_acknowledging(_channel, _method, _properties, body):
        held.append(body)

    _run_consumer(hold_without_acknowledging, seconds=1.5)
    # The consumer above closed its connection, so measure what it held while
    # connected: it was handed exactly the prefetch, no more.
    assert len(held) == 3


def test_a_message_that_cannot_be_parsed_goes_to_the_dead_letter_queue(queue):
    _publish(queue, [b"this is not a segment"])

    _run_consumer(consumer_module._on_message, until=lambda: _ready(queue) == 0)
    time.sleep(0.5)

    assert _ready(queue) == 0  # not requeued forever
    assert _ready(dead_letter_queue(queue)) == 1  # kept, where a person can look


# --- the live queue and its own consumer (OMNI-502) ---------------------------


def test_each_role_reads_its_own_queue():
    assert consumer_module.queues_for("files") == (settings.segment_queue, True)
    # Live frames only: not even the camera queue, so nothing waits in front of them.
    assert consumer_module.queues_for("live") == (settings.live_segment_queue, False)
    assert settings.live_segment_queue != settings.segment_queue


def test_the_live_consumer_stores_live_frames_and_leaves_the_file_queue_alone(queue, live_queue):
    camera_id = _camera()
    video_id = _video()
    _publish(queue, [_body(video_id, i) for i in range(5)])  # a recording, waiting
    _publish(live_queue, [_live_body(camera_id, 1_790_000_000.0 + i, i) for i in range(3)])

    live, _ = consumer_module.queues_for("live")
    _run_consumer(consumer_module._on_message, queue=live, until=lambda: len(_camera_rows(camera_id)) == 3)

    assert len(_camera_rows(camera_id)) == 3  # the live frames did not wait for the file
    time.sleep(0.5)
    assert _ready(live_queue) == 0
    assert _ready(queue) == 5 and _rows(video_id) == []  # not this consumer's to store


def test_the_file_consumer_does_not_take_live_frames(queue, live_queue):
    camera_id = _camera()
    _publish(live_queue, [_live_body(camera_id, 1_790_000_000.0)])

    files, _ = consumer_module.queues_for("files")
    _run_consumer(consumer_module._on_message, queue=files, seconds=1.5)

    assert _camera_rows(camera_id) == []
    assert _ready(live_queue) == 1


def test_a_live_frame_is_acknowledged_only_after_its_row_is_committed(live_queue, monkeypatch):
    """NFR-5 on the live queue: the same callback, so the same rule."""
    camera_id = _camera()
    _publish(live_queue, [_live_body(camera_id, 1_790_000_000.0)])

    def database_down(_body):
        raise RuntimeError("database is down")

    monkeypatch.setattr(consumer_module, "store_segment", database_down)
    error = _run_consumer(consumer_module._on_message, queue=live_queue)

    assert isinstance(error, RuntimeError)
    assert _ready(live_queue) == 1  # still there, not lost
    assert _camera_rows(camera_id) == []

    monkeypatch.setattr(consumer_module, "store_segment", store_segment)
    _run_consumer(consumer_module._on_message, queue=live_queue, until=lambda: _ready(live_queue) == 0)
    assert len(_camera_rows(camera_id)) == 1
