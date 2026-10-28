"""query's side of ai_workers' internal API (OMNI-707): a search query turned into a vector.

query never loads a model; ai_workers holds the encoders (OMNI-704, OMNI-706). Text vectors
are cached here by the exact query text (NFR-2: a repeated query skips encoding), per
encoder. Results are never cached: new frames arrive all the time.
"""

import threading
from collections import OrderedDict

import httpx

from app.settings import settings

# One per text encoder: the path on ai_workers and the model its vectors must come from.
FRAME_TEXT = "/encode/text"
CLIP_TEXT = "/encode/clip-text"


class AiWorkersUnavailableError(Exception):
    pass


class WrongModelError(Exception):
    """ai_workers answered with a vector of another model than the one pinned here: it
    would be compared with the stored vectors of the pinned one (D-30, D-33)."""


class TextVectorCache:
    """The last `size` query vectors, by encoder and exact text. Thread-safe: FastAPI runs
    sync routes on a thread pool."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._items: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> list[float] | None:
        with self._lock:
            vector = self._items.get(key)
            if vector is not None:
                self._items.move_to_end(key)
            return vector

    def put(self, key: tuple[str, str], vector: list[float]) -> None:
        with self._lock:
            self._items[key] = vector
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


cache = TextVectorCache(settings.search_text_cache_size)


def text_vector(text: str, *, path: str, model: str, model_revision: str) -> tuple[list[float], bool]:
    """The vector of `text` from ai_workers' encoder at `path`, and whether it came from the
    cache. Raises AiWorkersUnavailableError if ai_workers cannot answer, WrongModelError if
    it answers with another model."""
    key = (path, text)
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    try:
        response = httpx.post(
            f"{settings.ai_workers_base_url}{path}", json={"q": text}, timeout=settings.ai_workers_timeout_s
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        raise AiWorkersUnavailableError(str(exc)) from exc
    if (body["model"], body["model_revision"]) != (model, model_revision):
        raise WrongModelError(f"ai_workers encodes with {body['model']}@{body['model_revision']}, not {model}@{model_revision}")
    cache.put(key, body["vector"])
    return body["vector"], False
