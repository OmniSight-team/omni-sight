# OmniSight — Project Scaffold Prompt

> Paste this into Claude Code in an empty directory. Build the structure only — folders, configs, and tool initialization. **No application code, no algorithm logic.** Every Python module gets an empty `__init__.py`, every service entrypoint gets a one-line `# TODO Phase A/B` placeholder, nothing more.

---

## What to build

A monorepo for **OmniSight**, a distributed semantic video intelligence platform. Capstone project, B.Sc. Software Engineering, Braude College.

The repo must support:
- **Phase A** (this semester): ingestion service, two AI workers (frame + temporal embeddings), query API, dashboard.
- **Phase B** (next semester): PFM, agentic verification, RAG forensics, MCP server — scaffolded now as stubs so future work needs no restructuring.

---

## Stack

| Layer | Tool |
|---|---|
| Python | 3.11, managed by **uv** (workspace mode) |
| Python services | FastAPI / async workers (folders only for now) |
| Vector DB | Qdrant (Docker) |
| Message broker | RabbitMQ (Docker) |
| Frontend | **Next.js 15** (App Router, TypeScript, Turbopack) + **shadcn/ui** + **Tailwind CSS v4** |
| Orchestration | Docker Compose |
| Tooling | ruff, mypy, pytest, pre-commit |

---

## Directory tree to create

```
omnisight/
├── README.md
├── LICENSE                          # MIT
├── .gitignore
├── .env.example
├── .python-version                  # "3.11"
├── .pre-commit-config.yaml
├── pyproject.toml                   # uv workspace root (ruff + mypy + pytest config)
├── docker-compose.yml               # full stack (Phase B services commented out)
├── docker-compose.dev.yml           # only RabbitMQ + Qdrant for local dev
├── Makefile                         # setup / infra-up / infra-down / lint / test / dev
│
├── docs/
│   ├── book/                        # markdown sources of the project book
│   ├── diagrams/
│   │   ├── mermaid/                 # .mmd sources
│   │   └── rendered/                # .svg exports
│   └── design/
│       └── decision_log.md
│
├── libs/                            # shared Python packages (uv workspace members)
│   ├── omnisight_common/
│   │   ├── pyproject.toml
│   │   ├── src/omnisight_common/__init__.py
│   │   └── tests/
│   └── omnisight_messaging/
│       ├── pyproject.toml
│       ├── src/omnisight_messaging/__init__.py
│       └── tests/
│
├── services/
│   ├── ingestion/                   # Phase A
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/ingestion/__init__.py
│   │   └── tests/
│   │
│   ├── ai_worker_frame/             # Phase A — SigLIP 2
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/ai_worker_frame/__init__.py
│   │   └── tests/
│   │
│   ├── ai_worker_temporal/          # Phase A — InternVideo2
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/ai_worker_temporal/__init__.py
│   │   └── tests/
│   │
│   ├── query_service/               # Phase A — FastAPI
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/query_service/
│   │   │   ├── __init__.py
│   │   │   ├── api/__init__.py
│   │   │   ├── retrieval/__init__.py
│   │   │   └── mcp/__init__.py      # Phase B wrapper folder, empty for now
│   │   └── tests/
│   │
│   ├── pfm/                         # Phase B stub
│   │   ├── pyproject.toml
│   │   └── src/pfm/
│   │       ├── __init__.py
│   │       ├── heads/__init__.py
│   │       └── data/__init__.py
│   │
│   ├── verification/                # Phase B stub
│   │   ├── pyproject.toml
│   │   └── src/verification/__init__.py
│   │
│   ├── rag_forensics/               # Phase B stub
│   │   ├── pyproject.toml
│   │   └── src/rag_forensics/__init__.py
│   │
│   └── dashboard/                   # Phase A — Next.js 15 + shadcn/ui
│       └── (created via `pnpm create next-app` — see instructions below)
│
├── infra/
│   ├── docker/
│   │   ├── rabbitmq/
│   │   │   ├── definitions.json
│   │   │   └── rabbitmq.conf
│   │   └── qdrant/
│   │       └── config.yaml
│   └── scripts/                     # empty .gitkeep
│
├── data/                            # git-ignored except .gitkeep
│   ├── raw/.gitkeep
│   ├── processed/.gitkeep
│   ├── checkpoints/.gitkeep
│   └── outputs/.gitkeep
│
├── notebooks/                       # empty
│
├── tests/
│   ├── integration/
│   ├── chaos/
│   ├── performance/
│   └── fixtures/
│
├── evaluation/                      # empty .gitkeep
│
├── scripts/                         # bootstrap / demo shell scripts (empty for now)
│
└── .github/
    └── workflows/
        ├── ci.yml                   # ruff + mypy + pytest
        └── docker-build.yml
```

---

## Execution steps

Do these in order. Stop and report at the end — do not write any business logic.

### 1. Initialize the repo

```bash
git init
```

Create the directory tree above. Every leaf folder gets a `.gitkeep` if it would otherwise be empty.

### 2. Set up uv workspace

```bash
uv init --no-readme --no-pin-python --bare
echo "3.11" > .python-version
```

Edit the root `pyproject.toml` to declare the workspace:

```toml
[project]
name = "omnisight"
version = "0.1.0"
description = "Distributed Semantic Video Intelligence & Predictive Reasoning Platform"
requires-python = ">=3.11"

[tool.uv.workspace]
members = [
    "libs/omnisight_common",
    "libs/omnisight_messaging",
    "services/ingestion",
    "services/ai_worker_frame",
    "services/ai_worker_temporal",
    "services/query_service",
    "services/pfm",
    "services/verification",
    "services/rag_forensics",
]

[tool.uv.sources]
omnisight-common = { workspace = true }
omnisight-messaging = { workspace = true }

[dependency-groups]
dev = [
    "ruff>=0.7",
    "mypy>=1.13",
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "pre-commit>=4",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests", "libs/*/tests", "services/*/tests"]
asyncio_mode = "auto"
```

For **each** member in `libs/` and `services/` create a minimal `pyproject.toml`:

```toml
[project]
name = "<package-name>"            # e.g. "omnisight-common", "ai-worker-frame"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/<module_name>"]   # e.g. "src/omnisight_common"
```

Then run `uv sync --all-packages` to verify the workspace resolves cleanly.

### 3. Bootstrap the Next.js dashboard professionally

Run inside `services/dashboard/`:

```bash
cd services/dashboard
pnpm create next-app@latest . --typescript --tailwind --eslint --app --src-dir --turbopack --import-alias "@/*" --use-pnpm
```

Then install shadcn/ui (CLI: `shadcn@latest`, not the deprecated `shadcn-ui`):

```bash
pnpm dlx shadcn@latest init -d
```

Use defaults: New York style, neutral base color, CSS variables. This sets up `components.json`, `lib/utils.ts`, and the `cn()` helper.

Pre-install a sensible base set of shadcn components so future PRs just compose them:

```bash
pnpm dlx shadcn@latest add button input card dialog dropdown-menu sonner skeleton badge tabs separator
```

Also add common deps for a professional setup:

```bash
pnpm add @tanstack/react-query zod lucide-react clsx tailwind-merge
pnpm add -D prettier prettier-plugin-tailwindcss @types/node
```

Create `.prettierrc.json`:

```json
{
  "plugins": ["prettier-plugin-tailwindcss"],
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100
}
```

Leave the generated `src/app/page.tsx` as-is for now (it's the Next.js welcome page) — Phase A page implementation comes later.

### 4. Configs

Write these files with **structure only**, no logic:

- **`.gitignore`** — Python (`__pycache__`, `.venv`, `*.egg-info`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`), Node (`node_modules`, `.next`, `dist`), env (`.env`, `.env.local`), data (`data/raw/*`, `data/processed/*`, `data/checkpoints/*`, `data/outputs/*` with `!.gitkeep`), models (`*.pt`, `*.pth`, `*.safetensors`, `*.bin`, `*.ckpt`), IDE (`.vscode`, `.idea`, `.DS_Store`), Docker (`.docker-volumes/`).
- **`.env.example`** — placeholder vars: `RABBITMQ_URL`, `QDRANT_URL`, `LOG_LEVEL`. No real values.
- **`.pre-commit-config.yaml`** — ruff (lint + format), end-of-file-fixer, trailing-whitespace, check-yaml.
- **`docker-compose.dev.yml`** — only `rabbitmq:3.13-management` (ports 5672, 15672) and `qdrant/qdrant:v1.11.0` (ports 6333, 6334). Healthchecks on both. A `.docker-volumes/qdrant` bind mount.
- **`docker-compose.yml`** — same two services, plus commented-out blocks for every Phase A/B service (so they can be uncommented later when their Dockerfiles are real).
- **Service `Dockerfile`s** — for each Phase A service, a multi-stage Dockerfile based on `python:3.11-slim` with `uv` installed via `pip install uv`, copying the workspace and running `uv sync --frozen`. Phase B services skip the Dockerfile.
- **`Makefile`** — targets: `setup` (uv sync + pnpm install in dashboard + pre-commit install), `infra-up`, `infra-down`, `lint` (ruff + mypy), `format` (ruff format), `test` (pytest), `dev` (start dashboard in dev mode), `clean`.
- **`README.md`** — short: project description, Phase A vs B scope, quickstart (`make setup`, `make infra-up`, `make dev`), repo layout (depth-2 tree), stack table, team line, MIT license.
- **`LICENSE`** — MIT.
- **`.github/workflows/ci.yml`** — on push/PR: install uv, `uv sync --all-packages`, `uv run ruff check`, `uv run mypy`, `uv run pytest -q`.
- **`.github/workflows/docker-build.yml`** — build the four Phase A service images on push to main.
- **`docs/design/decision_log.md`** — empty heading "Architectural Decisions" with a placeholder line.

### 5. Verify

Run and report results:

```bash
uv sync --all-packages
uv run ruff check .
cd services/dashboard && pnpm install && pnpm build
```

All three must succeed.

### 6. Output

After finishing, print:
1. The directory tree at depth 3 (excluding `__pycache__`, `node_modules`, `.next`, `.venv`, `.docker-volumes`).
2. `uv sync` status.
3. `pnpm build` status.
4. Total file count.

---

## Rules

- **Folders and configs only.** No business logic, no algorithms, no FastAPI routes, no React components beyond what `create-next-app` and `shadcn add` generate.
- **Every Python package** has `src/<module>/__init__.py` with just `"""<package name>."""` as the docstring.
- **Every Phase B service** is a valid uv workspace member (importable, lint-clean) but its `__init__.py` contains only the docstring.
- **No invented files.** If something isn't in this prompt, don't create it.
- **Use `pnpm`** for the dashboard, not npm or yarn.
- **Use `shadcn@latest`**, never `shadcn-ui` (deprecated).

Begin.
