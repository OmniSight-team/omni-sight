# Operating OmniSight by hand

Where everything is, how it is stored, and the commands to run, inspect and reset the system.
All commands run in a terminal opened in the `phase-b` folder.

---

## 1. Start and stop

| What | Command |
|---|---|
| First time only: create the settings file | `cp .env.example .env`, then fill in the passwords |
| Start everything | `docker compose up -d` |
| Start after code changes (rebuild images) | `docker compose up -d --build` |
| See what is running and healthy | `docker compose ps` |
| Stop (keeps all data) | `docker compose stop` |
| Start again after a stop | `docker compose start` |
| Restart one service | `docker compose restart query` |
| Remove the containers (keeps all data) | `docker compose down` |
| **Remove containers and ALL data** | `docker compose down -v` (cannot be undone, see section 8) |
| Watch a service's log | `docker compose logs -f query` (Ctrl+C to stop watching) |
| Open a shell inside a service | `docker compose exec query bash` |

`ai-workers` takes about 1–2 minutes to load its models after a start; search answers "model
unavailable" until `docker compose ps` shows it **healthy**.

---

## 2. The services, and where to open them

| Service | Job | Open it at |
|---|---|---|
| `nginx` | HTTPS entry point | **https://localhost** (use this one) |
| `frontend` | The dashboard (Next.js) | http://localhost:3000 (playback only works through nginx) |
| `query` | The API: login, cameras, videos, search | http://localhost:8000/docs |
| `ingestion` | Reads every video and camera, runs the motion gate | (internal) |
| `consumer`, `consumer-live` | Store each frame's row (files, cameras) | (internal) |
| `ai-workers` | The models: SigLIP 2, InternVideo2 text, YOLO-World | (internal) |
| `postgres` | The database | `localhost:5432` (DBeaver) |
| `qdrant` | The vectors | (no port, see section 5) |
| `rabbitmq` | The queues between services | http://localhost:15672 |
| `mediamtx` | Simulated RTSP cameras | `rtsp://mediamtx:8554/…` (inside Docker) |

User names and passwords for Postgres, RabbitMQ and the admin login are in `.env`.

---

## 3. Where everything is stored

Data lives in **Docker volumes** (on your disk, managed by Docker), not in the project folder.

| Volume | Inside the containers | What it holds |
|---|---|---|
| `postgres_data` | `/var/lib/postgresql/data` | The database (section 4) |
| `video_storage` | `/data/videos` | Uploaded and dataset videos, as received |
| `frame_storage` | `/data/frames` | Full-size JPEG of every **kept** frame |
| `thumb_storage` | `/data/thumbs` | Small thumbnail of every kept frame |
| `preview_storage` | `/data/previews` | One current picture per live camera (overwritten) |
| `qdrant_data` | `/qdrant/storage` | The vectors (section 5) |
| `rabbitmq_data` | `/var/lib/rabbitmq` | Messages waiting in the queues |
| `frontend_node_modules` | `/app/node_modules` | Frontend packages (rebuilt, no data) |

**Folders in the project, not in Docker:**

| Folder | What it holds |
|---|---|
| `.env` | Settings and passwords (never committed) |
| `data/` | Local copy of the dataset clips the system loads (`/datasets` in `query`) |
| `datasets/` | Committed lists: splits, windows, hand-check and VIRAT samples |
| `models/pretrained/` | The downloaded model weights (SigLIP 2, InternVideo2, YOLO-World) |
| `infra/` | Config for nginx (incl. the HTTPS certificate), Qdrant, RabbitMQ, MediaMTX |

**How frame files are named:**

- An uploaded or dataset video: `/data/frames/<video_id>/<frame number, 6 digits>.jpg`, e.g.
  `/data/frames/3229/000137.jpg`; the thumbnail has the same name under `/data/thumbs/`
- A live camera: `/data/frames/camera-<camera_id>/<session>/<frame>.jpg`

Look at them: `docker compose exec query ls /data/frames` · copy one out:
`docker compose cp query:/data/frames/3229/000137.jpg .`

---

## 4. The database (Postgres)

Open it in DBeaver: host `localhost`, port `5432`, database, user and password from `.env`.

| Table | One row per | Main columns |
|---|---|---|
| `users` | account | email, role (operator, analyst, admin), lock state |
| `cameras` | camera | name, RTSP URL, state |
| `videos` | uploaded or dataset video | file path, size, length, fps, `source` (upload / dataset), `retention_until` |
| `segments` | frame (files: every frame; cameras: kept frames) | video or camera, time, motion score, kept or not and why, `frame_path`, `thumb_path` |
| `segment_hourly`, `camera_stats` | hour / camera | the dashboard's counts (kept up to date by triggers) |
| `dataset_manifest` | dataset clip (UCF-Crime, CCD, VIRAT) | dataset, clip name, event class and times, split, `video_id` if loaded |
| `event_windows` | lead-up window | start, end, class, split, **your hand-check verdict** |

Useful queries:

```sql
SELECT * FROM videos ORDER BY id;
SELECT video_id, count(*) AS frames, count(*) FILTER (WHERE frame_path IS NOT NULL) AS kept
  FROM segments GROUP BY video_id ORDER BY video_id;
```

---

## 5. The vectors (Qdrant)

| Collection | One point per | Size | Point id |
|---|---|---|---|
| `frame_vectors` | kept frame, **scene** vector (SigLIP 2) | 1152 numbers | the frame's `segments.id` |
| `clip_vectors` | kept frame, **action** vector (InternVideo2) | 512 numbers | the same `segments.id` |

Each point also carries: video or camera, time, source, dataset, frame and thumbnail paths, model.

Qdrant has no port open to your computer (on purpose). Ask it from inside `query`:

```bash
docker compose exec query uv run --package omnisight-query python -c "from qdrant_client import QdrantClient; c=QdrantClient('qdrant'); print({n: c.count(n).count for n in ['frame_vectors','clip_vectors']})"
```

Per-video progress is on screen: the "searchable so far" line under each video.

---

## 6. What happens to an upload, and where each step leaves its mark

| Step | Done by | Leaves |
|---|---|---|
| 1. The file arrives | `query` | a `videos` row; the file in `/data/videos` |
| 2. Every frame is checked by the motion gate (Algorithm 1) | `ingestion` | messages in RabbitMQ |
| 3. Each frame's row is written | `consumer` | `segments` rows; kept frames in `/data/frames` and `/data/thumbs` |
| 4. Each kept frame is encoded | `ai-workers` (about 9 s a frame on this laptop) | a point in `frame_vectors` |
| 5. Action vectors | Colab only (D-32), then `scripts/import_clip_vectors.py` | points in `clip_vectors` |

---

## 7. Scripts you will use

Run from `phase-b` with `uv run python scripts/<name>.py` (each script's top comment says how).

| Script | Does |
|---|---|
| `seed_admin.py` | Creates the admin account from `.env` |
| `copy_dataset_subsets.py` | Copies the chosen dataset clips from Drive into `data/` |
| `run_dataset_load.py <dataset>` | Loads them into the system |
| `import_frame_vectors.py`, `import_clip_vectors.py` | Copy vectors made on Colab from Drive into Qdrant |
| `backfill_embeddings.py` | Queues every kept frame that has no vector yet |
| `backfill_dashboard_rollup.py` | Rebuilds the dashboard counts |
| `uv run pytest` | All tests |

---

## 8. Resetting

**A. Everything** (users, cameras, datasets list, hand-check verdicts, footage, vectors):

```bash
docker compose down -v
docker compose up -d
uv run python scripts/seed_admin.py
```

**B. Footage only** (keeps users, cameras, the datasets list, windows and verdicts). Ask Claude
Code to check these steps against the code before the first time you run them:

1. In DBeaver: `DELETE FROM segments; DELETE FROM videos; TRUNCATE segment_hourly, camera_stats;`
2. Files: `docker compose exec query sh -c "rm -rf /data/videos/* /data/frames/* /data/thumbs/*"`
3. Vectors: delete the two collections (Qdrant), then `docker compose restart query`, which creates
   them again empty

---

## 9. My measurements

Fill in as you go through the system step by step.

| Date | What I did | What I measured | Result | Notes |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |
