# OmniSight — Phase B

Distributed semantic video intelligence and predictive reasoning platform.
Capstone project 26-2-D-17 · Ahmad Tawil · Cyrine Fahoum · Advisor: Dr. Reuven Cohen
Software Engineering, Braude College of Engineering.

The system watches many camera feeds at once, warns before an event finishes, answers
plain-language questions about recorded footage, and assembles incident reports whose every
statement links back to the video that supports it.

## What is in each folder

| Folder | Purpose |
|---|---|
| `services/common` | Shared contracts, settings and helpers. Every service imports this. |
| `services/ingestion` | Takes video in: live camera feeds and uploaded files. Keeps only frames with motion. |
| `services/ai_workers` | Turns frames and clips into searchable vectors. |
| `services/pfm` | Predicts events before they finish, and verifies alerts before an operator sees them. |
| `services/query` | The API behind the dashboard and behind external systems, including the MCP server. |
| `frontend` | The dashboard: live monitoring, search, alerts, incident reports. |
| `infra` | Config for the database, vector store, message queue and web server. |
| `data` | The five research datasets, one folder each. Never committed. |
| `models` | Downloaded checkpoints and the ones trained here. Never committed. |
| `notebooks` | Experiments and the charts that go into the project book. |
| `docs` | Design notes; `results.md` (every measurement, the week it is taken), `decisions.md`, `known-issues.md`. |
| `scripts` | Small one-off helpers. |
| `tests` | End-to-end checks across the whole system. |

## Running it

One server, one command. Nothing is exposed to the internet.

```
cp .env.example .env     # fill in passwords, storage path, retention days
docker compose up -d
```

Then open the dashboard on the local network, sign in, and add cameras by their RTSP URL.
To update later: `git pull` then `docker compose up -d` again.

## Python — uv workspace

All Python lives in one uv workspace so both of us resolve identical versions.
`uv.lock` is committed; that is what makes the two machines match.

```
uv sync                                  # set everything up
uv run pytest                            # run the tests
uv add fastapi --package omnisight-query # add a dependency to one service only
```

Each service keeps its own dependencies, so the `ai_workers` container is the only one that
ships PyTorch.

## Two things worth knowing

**Model weights are not in the repo.** They are far too large for GitHub. A fresh deployment
has no trained model until the weights are placed in `models/trained/`.

**`data/` is research datasets, not customer footage.** Recorded video on a running system
lives in a Docker volume, not here.
