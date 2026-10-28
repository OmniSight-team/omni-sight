"""`GET /search` on the running stack (OMNI-707): a few queries through the real API, each
twice (the second from the text-vector cache), with a date filter and a camera filter.

Runs inside `query` (it logs in as the admin from `.env`, never printing the password);
this script, run on the host, pipes itself in:

    docker compose up -d
    uv run python scripts/try_search.py ["a query" ...]

Prints, per query: the top hits (segment, video, camera, time, score), `elapsed_ms` and its
split (encode, search, join), whether the vector came from the cache, and `dropped`.
"""

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

QUERIES = ["a person walking across a parking lot", "a white car driving on the road", "a person carrying a bag"]
API = "http://localhost:8000"


def _inside(queries: list[str]) -> None:
    import os

    login = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(login) as response:
        token = json.load(response)["access_token"]

    def search(**params) -> tuple[int, dict]:
        url = f"{API}/search?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def show(label: str, status: int, body: dict) -> None:
        if status != 200:
            print(f"  {label}: {status} {body}")
            return
        t = body["timings"]
        print(f"  {label}: {body['total']} hits, dropped {body['dropped']}, elapsed {body['elapsed_ms']} ms "
              f"(encode {t['encode_ms']}{' cached' if t['encode_cached'] else ''}, search {t['search_ms']}, join {t['join_ms']})"
              f"{', ' + body['message'] if body['message'] else ''}")
        for hit in body["results"]:
            camera = hit["camera"]["name"] if hit["camera"] else "-"
            print(f"    segment {hit['segment_id']} video {hit['video_id']} camera {camera} "
                  f"t={hit['timestamp_s']:.2f}s {hit['captured_at']} score {hit['score']:.4f} {hit['thumb_url']}")

    for q in queries:
        print(f"q = {q!r}")
        show("first ", *search(q=q, k=5))
        show("repeat", *search(q=q, k=5))
    q = queries[0]
    status, body = search(q=q, k=1)
    if status == 200 and body["results"]:
        at = body["results"][0]["captured_at"]
        show("from/to around the top hit", *search(q=q, k=5, **{"from": at, "to": at}))
        show("from after the top hit", *search(q=q, k=5, **{"from": "2100-01-01T00:00:00Z"}))
    show("camera 1", *search(q=q, k=5, camera_id=1))
    show("mode=fused", *search(q=q, mode="fused"))
    show("empty q", *search(q="  "))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--inside"]:
        _inside(args[1:] or QUERIES)
        sys.exit(0)
    sys.exit(subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "python", "-", "--inside", *args],
        input=Path(__file__).read_bytes(),
    ).returncode)
