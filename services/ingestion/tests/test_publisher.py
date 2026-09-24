"""OMNI-311: publishing gated frames to the durable queue.

Needs RabbitMQ up (`docker compose up -d rabbitmq`). No mocks: these talk to
the real broker, on a queue of their own per test so they never compete with
the running consumer for the real one.

publisher.py and pipeline.py are loaded by file path under their own names, the
same way the other ingestion tests do it — ingestion and query both have a
top-level package called `app`.
"""

import base64
import importlib.util
import json
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pika
import pytest
from omnisight_common import CommonSettings, SegmentMessage, connection_parameters
from omnisight_common.segment_queue import dead_letter_queue

APP = Path(__file__).resolve().parents[1] / "app"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = _load("omnisight_ingestion_pipeline_for_publisher", "pipeline.py")
publisher = _load("omnisight_ingestion_publisher", "publisher.py")

SETTINGS = CommonSettings()
PARAMS = connection_parameters(SETTINGS)


@pytest.fixture
def queue():
    name = f"omni311-test-{uuid.uuid4().hex[:12]}"
    yield name
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.queue_delete(name)
        channel.queue_delete(dead_letter_queue(name))


def _record(index: int, *, admitted: bool = True):
    return pipeline.SegmentRecord(
        video_id=7,
        camera_id=None,
        frame_index=index,
        timestamp_s=index / 30,
        frame_path=f"/data/frames/7/{index:06d}.jpg" if admitted else None,
        thumb_path=f"/data/thumbs/7/{index:06d}.jpg" if admitted else None,
        motion_score=3.0,
        admitted=admitted,
        source_type="upload",
        clip_start_s=0.0 if admitted else None,
        clip_end_s=index / 30 if admitted else None,
        admission_reason="motion" if admitted else None,
    )


def _publish(records, queue, extraction_id="run-1"):
    return publisher.publish_segments(
        records, extraction_id, connection_params=PARAMS, queue=queue
    )


def _drain(queue):
    """Every message currently in the queue, as (properties, body)."""
    messages = []
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        while True:
            method, properties, body = channel.basic_get(queue, auto_ack=True)
            if method is None:
                return messages
            messages.append((properties, body))


def _management(path: str) -> dict:
    request = urllib.request.Request(f"http://{SETTINGS.rabbitmq_host}:15672/api/{path}")
    token = base64.b64encode(f"{SETTINGS.rabbitmq_user}:{SETTINGS.rabbitmq_password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def test_every_record_becomes_one_message_carrying_the_records_fields(queue):
    records = [_record(i, admitted=i % 2 == 0) for i in range(6)]

    assert _publish(records, queue) == 6

    messages = _drain(queue)
    assert len(messages) == 6
    for record, (_properties, body) in zip(records, messages, strict=True):
        message = SegmentMessage.model_validate_json(body)
        assert message.frame_index == record.frame_index
        assert message.admitted == record.admitted
        assert message.frame_path == record.frame_path
        assert message.motion_score == record.motion_score
        assert message.extraction_id == "run-1"


def test_every_message_is_persistent(queue):
    _publish([_record(i) for i in range(4)], queue)

    messages = _drain(queue)
    assert len(messages) == 4
    # delivery_mode 2 is what makes the broker write it to disk; without it a
    # broker restart loses the message even though the queue itself survives.
    assert {properties.delivery_mode for properties, _ in messages} == {2}


def test_the_queue_is_durable_and_dead_letters_into_its_own_queue(queue):
    _publish([_record(0)], queue)

    info = _management(f"queues/%2F/{urllib.parse.quote(queue, safe='')}")
    assert info["durable"] is True
    assert info["arguments"]["x-dead-letter-routing-key"] == dead_letter_queue(queue)
    dead = _management(f"queues/%2F/{urllib.parse.quote(dead_letter_queue(queue), safe='')}")
    assert dead["durable"] is True


def test_publishing_is_repeatable_on_an_existing_queue(queue):
    _publish([_record(0)], queue)
    _publish([_record(1)], queue)  # redeclaring with the same arguments must not fail

    assert len(_drain(queue)) == 2


def test_a_broker_that_cannot_be_reached_is_an_error_not_a_silent_loss(queue):
    unreachable = pika.ConnectionParameters(
        host=SETTINGS.rabbitmq_host,
        port=1,  # nothing listens here
        credentials=PARAMS.credentials,
        connection_attempts=1,
        socket_timeout=2,
    )

    with pytest.raises(publisher.PublishError):
        publisher.publish_segments(
            [_record(0)], "run-1", connection_params=unreachable, queue=queue
        )


def test_records_are_consumed_lazily_so_a_failure_reports_how_far_it_got(queue):
    def records():
        yield _record(0)
        yield _record(1)
        raise RuntimeError("decoder blew up")

    with pytest.raises(RuntimeError):
        _publish(records(), queue)

    # The two before the failure were confirmed and stay queued; the caller was
    # told by the exception, and the consumer drops them if that run failed.
    assert len(_drain(queue)) == 2
