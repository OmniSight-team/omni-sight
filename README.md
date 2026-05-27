<div align="center">

# OmniSight

**Distributed Semantic Video Intelligence & Predictive Reasoning Platform**

B.Sc. Software Engineering Capstone · Braude College of Engineering

Ahmad Tawil · Cyrine Fahoum · Supervisor: Dr. Reuven Cohen

---

[![CI](https://github.com/your-org/omni-sight/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/omni-sight/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://github.com/astral-sh/uv)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-black)](https://nextjs.org/)

</div>

---

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [empirical contribution](#novel-contribution)
- [System Architecture](#system-architecture)
- [Core Capabilities](#core-capabilities)
- [Algorithms](#algorithms)
- [Datasets](#datasets)
- [Success Metrics](#success-metrics)
- [Requirements](#requirements)
- [Tech Stack](#tech-stack)
- [Repository Layout](#repository-layout)
- [Quickstart](#quickstart)
- [Phase Roadmap](#phase-roadmap)
- [Team](#team)
- [License](#license)

---

## Overview

Modern video infrastructure produces footage faster than humans can review it. Surveillance, sports, and traffic cameras run continuously, yet the moments that matter remain buried in archives searched by timestamp rather than by meaning — the **dark-data problem**.

**OmniSight** is a distributed platform that brings semantic retrieval, predictive forecasting, agentic verification, and forensic reconstruction into a single end-to-end pipeline. It ingests live and uploaded video, indexes each segment through dual semantic and temporal embeddings, and serves natural-language search at sub-second latency. It does not just find what already happened — it anticipates what is about to happen.

---

## The Problem

| Pain Point | Current Reality | OmniSight's Answer |
|---|---|---|
| Footage is indexed by timestamp | Finding an event means watching hours of video | Natural-language semantic search over meaning, not metadata |
| Anomalies are detected after the fact | Operators react, they cannot prevent | Predictive forecasting fires ≥ 15 s before an event completes |
| Every detection candidate reaches a human | Alert fatigue, high false-alarm rates | Four-tier agentic verification suppresses false positives |
| Incident reconstruction is manual | Investigators stitch footage by hand | Multimodal RAG synthesizes an evidence-grounded dossier automatically |
| AI capabilities are siloed | Integration requires bespoke engineering per tool | MCP server exposes all capabilities to any external AI agent |

---

## empirical contribution

The scientific core of OmniSight is the **Predictive Forecasting Module (PFM)** — a shared temporal-transformer backbone with three lightweight domain heads (surveillance, sports, traffic) trained jointly — and its **cross-domain transfer protocol**.

**Hypothesis:** Pre-training the shared backbone on two domains produces transferable temporal representations that lift accuracy on a held-out third domain over training from scratch on it alone.

**Protocol:** Train backbone + heads jointly on {d₁, d₂} → freeze backbone → fine-tune a fresh head for d₃ on a k-shot subset (10%) → measure Top-3 accuracy → compare against a from-scratch baseline. Repeated for all three holdout combinations. Acceptance criterion **SM-5**: ≥ 10 % Top-3 accuracy lift averaged across holdouts. A negative result is reported as a genuine empirical finding.

---

## System Architecture

### Deployment Overview

> **Diagram placeholder** — high-level deployment diagram will be added here.
>
> _Three-tier layout: Frontend (Nginx → React Dashboard) → Backend (Ingestion Engine · AI Workers · PFM + Verification · Query Service) ↔ RabbitMQ ↔ Data Tier (Qdrant · PostgreSQL). External operators connect over HTTPS; external AI agents connect via MCP/JSON-RPC._

### Use Case Diagram

> **Diagram placeholder** — use case diagram will be added here.
>
> _Actors: User (operator/analyst), System Administrator, External AI Agent. Authenticate is a mandatory include for all user and admin actions; Invoke MCP Tool is mandatory for all agent actions._

### MCP Server Integration

> **Diagram placeholder** — MCP server interaction diagram will be added here.
>
> _Each external agent holds a stateful JSON-RPC 2.0 session over Streamable HTTP/SSE. Server advertises four primitives: `search_video_semantics`, `analyze_temporal_action`, `get_predictive_alerts` (tools) and `live_alert_stream` (streaming resource)._

---

## Core Capabilities

### 1 · Semantic Video Ingestion (Phase A)

- Accepts **RTSP live streams** and **uploaded video files**
- **ROI-Aware Spatial-Motion Sampling** (Algorithm 1) selects informative frames using a G×G grid motion filter — discarding static footage before it reaches the GPU
- Selected frames and their causal clip windows are published to a **RabbitMQ** work queue for asynchronous, decoupled processing

### 2 · Dual-Stream Embedding (Phase A)

Two asynchronous AI workers process every admitted payload in parallel:

| Worker | Model | Output | Captures |
|---|---|---|---|
| `ai_worker_frame` | **SigLIP 2** | 1 152-D L2-normalized vector | Static scene semantics |
| `ai_worker_temporal` | **InternVideo2** | 768-D L2-normalized vector | Motion & event structure |

Both embeddings are upserted into **Qdrant** with shared metadata (timestamp, camera ID, thumbnail reference) so they can be joined during retrieval.

### 3 · Natural-Language Semantic Search (Phase A)

- A text query is encoded by both model text encoders simultaneously
- A classifier routes scene-centric vs. action-centric queries, weighting each retriever accordingly
- **Reciprocal Rank Fusion (RRF)** (Cormack et al., 2009, k₀ = 60) fuses rank positions from both retrievers — scale-invariant and robust to retriever score drift
- End-to-end query latency target: **< 3 s** (NFR-2)

### 4 · Predictive Forecasting Module — PFM (Phase B)

- A shared **temporal-transformer backbone** consumes a sliding window (30–60 s) of InternVideo2 clip embeddings
- Three lightweight **domain adapter heads** — surveillance, sports, traffic — output event-type probabilities, time-to-event Δt, and a confidence score κ
- Joint training loss: `L = Σ_d λ_d · [CE(p_d, y_d) + α · MSE(Δt_d, τ_d)]`
- New domain heads can be added without modifying the backbone (NFR-7b)

### 5 · Four-Tier Agentic Verification (Phase B)

Continuous embeddings are filtered by a cost-sorted cascade that escalates only high-confidence candidates:

| Tier | Component | Action |
|---|---|---|
| 1 | Concept-vector trigger | Cheap similarity gate — suppress obvious non-events |
| 2 | PFM | Gate on max(p) and κ |
| 3 | **Qwen2.5-VL** | Chain-of-Causation verdict over 8 sampled frames |
| 4 | Operator | Human confirmation before alert is issued |

All tiers operate on causal windows (Algorithm 1), eliminating lookahead latency.

### 6 · Multimodal RAG Forensic Synthesis (Phase B)

After operator confirmation, the RAG engine reconstructs an evidence-grounded dossier:

1. Query combines the Chain-of-Causation summary (text) with the triggering clip vector
2. Retrieval scoped by Qdrant payload filter to a time window `[t − R, t + R]` around the incident
3. Cross-camera correlation bins evidence into 2-second windows across FOV-overlapping cameras
4. A generative LLM assembles a structured report — every claim cited to a retrieved segment

### 7 · MCP Server & Dashboard (Phase A/B)

- **FastMCP** exposes all capabilities to external AI agents via JSON-RPC 2.0 over Streamable HTTP/SSE
- **Next.js 15** dashboard (App Router, Turbopack) provides natural-language search, real-time alert display, and dossier viewing for human operators

---

## Algorithms

Six formal algorithms are specified in the project book (pseudocode in Appendix A):

| # | Algorithm | Stage |
|---|---|---|
| 1 | **ROI-Aware Spatial-Motion Sampling** | Ingestion — selects informative frames via G×G grid motion filter |
| 2 | **Dual-Stream Embedding Generation** | AI Workers — SigLIP 2 (frame) + InternVideo2 (clip), L2-normalized |
| 3 | **Dual-Model Score Fusion (RRF)** | Query Service — reciprocal rank fusion, k₀ = 60 |
| 4 | **PFM Inference** | Forecasting — transformer backbone + domain heads → p, Δt, κ |
| 5 | **Four-Tier Agentic Verification** | Verification — cascade: concept → PFM → VLM → operator |
| 6 | **Multimodal RAG Forensic Synthesis** | RAG — time-windowed retrieval + cross-camera correlation + cited generation |

> **Algorithm flow diagram placeholder** — end-to-end pipeline diagram connecting Algorithms 1–6 will be added here.

---

## Datasets

| Dataset | Domain | Size | Role in OmniSight | Key Metrics |
|---|---|---|---|---|
| **VIRAT** (Oh et al., 2011) | Surveillance | Stationary outdoor cameras | Ingestion, embedding, semantic search evaluation | SM-1 |
| **UCF-Crime** (Sultani et al., 2018) | Surveillance | ~1 900 untrimmed CCTV videos, 13 anomaly classes | PFM surveillance head training, verification evaluation | SM-2, SM-4 |
| **SoccerNet** (Giancola et al., 2018) | Sports | Dense timestamped broadcast events | PFM sports head training, cross-domain transfer | SM-2, SM-5 |
| **DoTA** (Yao et al., 2022) | Traffic | 4 677 dash-cam videos, explicit anomaly start/end | PFM traffic head training, early-warning time measurement | SM-2, SM-3, SM-5 |
| **AI City Challenge** (2025) | Traffic | Multi-camera, synchronized viewpoints | Cross-camera forensic dossier validation | SM-6 |

---

## Success Metrics

| ID | Metric | Criterion | Dataset |
|---|---|---|---|
| **SM-1** | Semantic search quality | Top-5 recall ≥ 85 % on NL queries + lift over frame-only baseline | VIRAT |
| **SM-2** | Prediction accuracy | Top-3 accuracy ≥ 70 % per domain | UCF-Crime, SoccerNet, DoTA |
| **SM-3** | Early warning time | Alert fires ≥ 15 s before event onset | DoTA |
| **SM-4** | False alarm rate | False positives ≤ 20 % per domain | UCF-Crime (including normal footage) |
| **SM-5** | Cross-domain transfer | ≥ 10 % Top-3 lift over from-scratch baseline, averaged across holdouts | All three, each held out once |
| **SM-6** | Forensic report generation | ≥ 2 multi-camera dossiers with correct cameras, chronology, and cited evidence | AI City Challenge |

---

## Requirements

### Functional Requirements

| ID | Requirement |
|---|---|
| FR-1a | Ingest video from RTSP streams and uploaded files |
| FR-1b | Select informative frames based on detected motion activity |
| FR-1c | Publish selected frames to an asynchronous processing queue |
| FR-2 | Generate frame-level (SigLIP 2) and clip-level (InternVideo2) embeddings |
| FR-3 | Store embeddings with metadata (timestamp, camera ID, thumbnail) in Qdrant |
| FR-4 | Accept NL queries, encode them, and return RRF-ranked results |
| FR-5 | PFM: output event-type probabilities, Δt, and κ over 30–60 s sliding windows |
| FR-6 | Verify alerts through the four-tier agentic cascade before operator escalation |
| FR-7 | Generate structured forensic dossiers via multimodal RAG |
| FR-8 | Expose all capabilities as an MCP-compliant server |
| FR-9 | Provide a web dashboard for search, alerts, and dossier viewing |
| FR-10 | Enforce authentication on all API, MCP, and dashboard endpoints |
| FR-11 | Automatically retry failed operations; route terminal failures to dead-letter queue |

### Non-Functional Requirements (ISO 25010)

| ID | Attribute | Requirement | Target |
|---|---|---|---|
| NFR-1 | Performance | Frame capture → searchable entry latency | < 5 s |
| NFR-2 | Performance | Semantic search query response time | < 3 s |
| NFR-3 | Performance | PFM inference per sliding window | < 2 s |
| NFR-4 | Performance | Concurrent streams without degradation | ≥ 10 |
| NFR-5 | Reliability | Data loss during component failures | 0 embeddings lost |
| NFR-6 | Security | Auth + RBAC enforcement | 100 % of endpoints |
| NFR-7a | Maintainability | Services independently deployable | All containerized |
| NFR-7b | Maintainability | New PFM domain heads addable without backbone changes | Verified by extension |
| NFR-8 | Portability | Full system deployable via single orchestration command | `docker compose up` |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Python runtime** | Python 3.11, managed by [uv](https://github.com/astral-sh/uv) (workspace mode) |
| **Backend services** | FastAPI, async workers |
| **Frame embeddings** | SigLIP 2 (Tschannen et al., 2025) — 1 152-D |
| **Temporal embeddings** | InternVideo2 (Wang et al., 2024) — 768-D |
| **Agentic reasoning** | Qwen2.5-VL (Bai et al., 2025) |
| **Vector database** | Qdrant v1.11 — HNSW cosine index |
| **Message broker** | RabbitMQ 3.13 — topic exchange, DLQ, 10-min TTL |
| **MCP server** | FastMCP — JSON-RPC 2.0 over Streamable HTTP/SSE |
| **Frontend** | Next.js 15 (App Router, Turbopack), TypeScript, Tailwind CSS v4, shadcn/ui |
| **Orchestration** | Docker Compose |
| **Tooling** | ruff, mypy (strict), pytest, pytest-asyncio, pre-commit |

---

## Repository Layout

```
omni-sight/
├── libs/
│   ├── omnisight_common/       # shared config, NFR constants, utilities
│   └── omnisight_messaging/    # RabbitMQ topology (exchange, queues, DLQ)
├── services/
│   ├── ingestion/              # Phase A — ROI-aware frame sampling + queue publish
│   ├── ai_worker_frame/        # Phase A — SigLIP 2 embeddings (1 152-D)
│   ├── ai_worker_temporal/     # Phase A — InternVideo2 clip embeddings (768-D)
│   ├── query_service/          # Phase A — FastAPI REST + FastMCP server
│   │   ├── api/                # REST endpoints
│   │   ├── retrieval/          # RRF fusion logic
│   │   └── mcp/                # MCP primitives (Phase B)
│   ├── pfm/                    # Phase B stub — transformer backbone + domain heads
│   ├── verification/           # Phase B stub — four-tier agentic cascade
│   │   ├── tiers/              # tier1_vector_trigger · tier2_pfm_gate · tier3_vlm_causation · tier4_escalation
│   │   └── pipeline.py         # Algorithm 5 orchestrator
│   ├── rag_forensics/          # Phase B stub — multimodal RAG dossier engine
│   └── dashboard/              # Phase A — Next.js 15 web dashboard
├── infra/
│   └── docker/                 # RabbitMQ config + Qdrant config
├── tests/
│   ├── integration/
│   ├── chaos/
│   └── performance/
├── docs/
│   ├── book/                   # project book sources
│   ├── diagrams/               # Mermaid sources + rendered SVGs
│   └── design/decision_log.md
├── data/                       # git-ignored — raw / processed / checkpoints / outputs
├── docker-compose.yml          # full stack
├── docker-compose.dev.yml      # RabbitMQ + Qdrant only (local dev)
├── Makefile
└── pyproject.toml              # uv workspace root
```

---

## Quickstart

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for RabbitMQ + Qdrant)
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- [pnpm](https://pnpm.io/) — `npm install -g pnpm`
- Python 3.11

### Setup

```bash
# 1. Clone
git clone https://github.com/your-org/omni-sight.git
cd omni-sight

# 2. Install all Python dependencies + dashboard packages + git hooks
make setup

# 3. Start infrastructure (RabbitMQ + Qdrant)
make infra-up

# 4. Launch the dashboard in dev mode
make dev
```

The dashboard will be available at `http://localhost:3000`.

### Common Commands

| Command | Description |
|---|---|
| `make setup` | Install all deps + pre-commit hooks |
| `make infra-up` | Start RabbitMQ + Qdrant via Docker Compose |
| `make infra-down` | Stop infrastructure containers |
| `make lint` | Run ruff + mypy |
| `make format` | Auto-format with ruff |
| `make test` | Run pytest across all workspace members |
| `make dev` | Start Next.js dashboard in dev mode (Turbopack) |
| `make clean` | Remove caches and build artifacts |

---

## Phase Roadmap

| Phase | Semester | Deliverables | Status |
|---|---|---|---|
| **Phase A** | Current | Architecture design, six formal algorithms, dataset selection, test plan, full monorepo scaffold | Complete |
| **Phase B** | Next | Implementation of all services, PFM training + cross-domain transfer evaluation, empirical results against SM-1 – SM-6 | Planned |

### Phase A Deliverables

- [x] Project book (design, literature review, algorithms, test plan)
- [x] System and deployment architecture diagrams
- [x] Six formal algorithms with pseudocode
- [x] Dataset selection with alignment to acceptance criteria
- [x] Full monorepo scaffold (uv workspace, Next.js dashboard, Docker Compose, CI)

### Phase B Backlog (preview)

- [ ] `ingestion` — implement Algorithm 1 (ROI-aware frame sampling, RabbitMQ publish)
- [ ] `ai_worker_frame` — SigLIP 2 inference + Qdrant upsert
- [ ] `ai_worker_temporal` — InternVideo2 inference + Qdrant upsert
- [ ] `query_service` — Algorithm 3 (RRF fusion), FastAPI endpoints, FastMCP primitives
- [ ] `pfm` — Algorithm 4 (transformer backbone + domain heads), cross-domain training
- [ ] `verification` — Algorithm 5 (four-tier cascade, Qwen2.5-VL integration)
- [ ] `rag_forensics` — Algorithm 6 (time-windowed retrieval, cross-camera correlation, cited generation)
- [ ] Evaluation against SM-1 – SM-6

---

## Team

| Name | Role |
|---|---|
| **Ahmad Tawil** | Co-developer |
| **Cyrine Fahoum** | Co-developer |
| **Dr. Reuven Cohen** | Academic Supervisor |

Department of Software Engineering, Braude College of Engineering

---

## License

MIT — see [LICENSE](LICENSE).
