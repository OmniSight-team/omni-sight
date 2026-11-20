"""Add videos made ready on Colab, with both of their vectors (OMNI-X05).

`notebooks/encode_upload_gpu.ipynb` leaves one folder per video in `G:/My Drive/omnisight/ready/`,
named by the video's fingerprint (the SHA-256 of the file, D-47): the video file, `vectors.npz`
(scene and action vector of every admitted frame) and `info.json` (file name, model pins, gate
settings). This script lists them and adds the ones chosen:

    docker compose up -d
    uv run python scripts/add_from_drive.py              # list the ready videos
    uv run python scripts/add_from_drive.py 1 3          # add numbers 1 and 3 of the list
    uv run python scripts/add_from_drive.py all          # add every one not fully in yet
    uv run python scripts/add_from_drive.py 8a096b72     # or by the start of a fingerprint

Adding copies the folder into `query` (as the VIRAT imports do: Docker Desktop cannot see Google
Drive's `G:`, so nothing is mounted) and runs `app.colab_vectors.add_ready` there:

- **new:** the video is stored as an upload is, extracted with the same gate, and both vectors
  imported by frame index; no CPU encode
- **already in the system** (the same file uploaded normally, under any name): extracted with
  the vectors if it never was, otherwise its vectors are imported

Refused if made with other model pins or other gate settings; nothing imported unless every
admitted frame matches a row of `vectors.npz` and every row a frame (the frames then go to the
CPU encoder instead). A frame or clip that already has a point of the pinned model is left
alone, so adding the same video twice changes nothing.

`--from DIR` reads another folder than Drive's. Exits non-zero if any video chosen was not
added in full.
"""

import json
import subprocess
import sys
from pathlib import Path

READY = Path("G:/My Drive/omnisight/ready")
INSIDE = "/tmp/add_from_drive"
MARK = "ADD_FROM_DRIVE "

# --- inside query ---------------------------------------------------------------------------


def _inside(command: str, args: list[str]) -> int:
    sys.path.insert(0, "/workspace/services/query")
    from app import colab_vectors

    if command == "status":
        print(MARK + json.dumps(colab_vectors.status(args)))
        return 0
    [fingerprint] = args
    print(MARK + json.dumps(colab_vectors.add_ready(Path(INSIDE) / fingerprint)))
    return 0


# --- on the host ----------------------------------------------------------------------------


def ready_folders(root: Path) -> list[tuple[Path, dict]]:
    """Finished folders only: one still being written is `{fingerprint}.part` or has no
    info.json yet."""
    found = []
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        info = folder / "info.json"
        if folder.is_dir() and not folder.name.endswith(".part") and info.is_file():
            found.append((folder, json.loads(info.read_text(encoding="utf-8"))))
    return sorted(found, key=lambda item: (item[1]["file"].lower(), item[0].name))


def choose(picks: list[str], folders: list[tuple[Path, dict]], states: dict) -> list[tuple[Path, dict]]:
    """Numbers of the list (from 1), `all` (every one not fully in), or fingerprint starts."""
    chosen = []
    for pick in picks:
        if pick == "all":
            chosen += [f for f in folders if not _complete(states.get(f[0].name, {}))]
        elif pick.isdigit() and len(pick) < 6:
            n = int(pick)
            if not 1 <= n <= len(folders):
                sys.exit(f"no number {n}: the list has {len(folders)}")
            chosen.append(folders[n - 1])
        else:
            match = [f for f in folders if f[0].name.startswith(pick.lower())]
            if len(match) != 1:
                sys.exit(f"{pick!r} matches {len(match)} ready videos")
            chosen += match
    seen, unique = set(), []
    for folder in chosen:
        if folder[0].name not in seen:
            seen.add(folder[0].name)
            unique.append(folder)
    return unique


def _complete(state: dict) -> bool:
    return (
        state.get("video_id") is not None
        and state.get("admitted", 0) > 0
        and state["frame_vectors"] == state["clip_vectors"] == state["admitted"]
    )


def describe(state: dict) -> str:
    if state.get("video_id") is None:
        return "new"
    where = f"in the system (video {state['video_id']})"
    if state["admitted"] == 0:
        return f"{where}, not extracted yet"
    if _complete(state):
        return f"{where}, scene + action in"
    return f"{where}, scene {state['frame_vectors']}/{state['admitted']}, action {state['clip_vectors']}/{state['admitted']}"


def _compose(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], **kwargs)


def _run_inside(*args: str) -> dict:
    done = _compose(
        "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside", *args,
        input=Path(__file__).read_bytes(), capture_output=True, check=False,
    )
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith(MARK):
            return json.loads(line[len(MARK):])
    sys.stderr.write(done.stdout.decode("utf-8", "replace")[-3000:] + done.stderr.decode("utf-8", "replace")[-3000:])
    raise RuntimeError(f"query did not answer {args[0]}")


def add(folder: Path) -> dict:
    _compose("exec", "-T", "query", "mkdir", "-p", INSIDE, check=True)
    try:
        _compose("cp", str(folder), f"query:{INSIDE}/{folder.name}", check=True, capture_output=True)
        return _run_inside("add", folder.name)
    finally:
        _compose("exec", "-T", "query", "rm", "-rf", f"{INSIDE}/{folder.name}", check=False)


def main(argv: list[str]) -> int:
    root = READY
    if "--from" in argv:
        i = argv.index("--from")
        root, argv = Path(argv[i + 1]), argv[:i] + argv[i + 2:]
    if not root.is_dir():
        sys.exit(f"{root} not found: is Google Drive for desktop running?")
    folders = ready_folders(root)
    if not folders:
        print(f"no ready videos in {root}")
        return 0
    states = _run_inside("status", *[folder.name for folder, _ in folders])

    if not argv:
        print(f"{len(folders)} ready videos in {root}:")
        for n, (folder, info) in enumerate(folders, 1):
            print(f"{n:3}  {info['file']}  {info.get('duration_s', 0):.0f} s, {info['admitted']} frames kept, "
                  f"scene + action ready  [{folder.name[:12]}]  {describe(states[folder.name])}")
        print("add with: uv run python scripts/add_from_drive.py <numbers> | all")
        return 0

    chosen = choose(argv, folders, states)
    if not chosen:
        print("nothing to add: every ready video is in with both vectors")
    ok = True
    for folder, info in chosen:
        result = add(folder)
        line = f"{info['file']} [{folder.name[:12]}]: {result['result']}"
        if result.get("video_id") is not None:
            line += f", video {result['video_id']}"
        if "admitted" in result:
            line += f", {result['admitted']} frames, scene {result['frame_vectors']}, action {result['clip_vectors']}"
        if result.get("problem"):
            line += f"  ({result['problem']})"
        print(line)
        ok &= result["result"] in ("added", "existing") and _complete(result | {"video_id": result.get("video_id")})
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inside"]:
        sys.exit(_inside(sys.argv[2], sys.argv[3:]))
    sys.exit(main(sys.argv[1:]))
