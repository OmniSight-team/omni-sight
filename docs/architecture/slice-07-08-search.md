# Slices 7 and 8 · Search: two vectors per frame, one fused answer

Every admitted frame gets a scene vector (SigLIP 2) and an action vector (InternVideo2), and a
sentence typed in the player finds the moments: the sentence is encoded by both models, each
vector collection is searched with the video's filter inside the search, and Algorithm 3 merges
the two lists by rank. Built in OMNI-700 to OMNI-717.

```mermaid
flowchart LR
    subgraph ingest["Ingestion + consumer"]
        GATE["Algorithm 1 gate<br/>every frame gated, JPEG stored"]
        SEG["consumer stores the segment<br/>(Postgres, ack after commit)"]
    end

    EQ[["RabbitMQ omnisight.embed<br/>one job per admitted frame<br/>+ embed.dead (D-34)"]]

    subgraph aiw["services/ai_workers (the only service that touches a model)"]
        EW["EmbedWorker<br/>batch, encode, upsert, then ack"]
        SIG["SigLIP 2 (pinned)<br/>image 1152-D · text"]
        IV["InternVideo2_CLIP_S (pinned, D-33)<br/>text side only on the laptop (D-32)"]
    end

    subgraph qd["Qdrant (cosine, HNSW)"]
        FV[("frame_vectors<br/>point id = segment id<br/>payload + indexes")]
        CV[("clip_vectors<br/>same ids, same payload")]
    end

    subgraph colab["Colab GPU (D-26) + Google Drive"]
        ARCH["VIRAT archive: 275 videos, 35,704 frames<br/>both vectors per frame, manifest + pins"]
        SM1["scripts/measure_sm1.py<br/>50 labelled queries"]
    end

    subgraph query["services/query"]
        IMP["import_clip_vectors.py<br/>import_frame_vectors.py (K-27)"]
        SRCH["GET /search?mode=frame|clip|fused<br/>video_id / camera_id / dates"]
        CLS["modality classifier (D-38)<br/>tuned_weights (D-40)<br/>fuse: reciprocal rank, B.3"]
        JOIN["Postgres join<br/>segment, video, thumb"]
        MET["GET /metrics/sm1"]
    end

    subgraph browser["Browser"]
        MS["search panel under the player and the live viewer<br/>Scene / Action / Combined, or Compare: three columns<br/>click: seek the player to that second"]
    end

    GATE --> SEG --> EQ --> EW
    EW --> SIG -->|"frame vector"| FV
    ARCH -->|"embeddings/product/*.npz"| IMP
    IMP --> FV
    IMP --> CV
    ARCH --> SM1 --> MET
    MS --> SRCH
    SRCH -->|"text"| SIG
    SRCH -->|"text"| IV
    SRCH -->|"search, filter inside"| FV
    SRCH -->|"search, filter inside"| CV
    SRCH --> CLS --> JOIN --> MS
    MET -.numbers.-> MS
```

## What to know when reading it

- **Every admitted frame gets a vector.** Nothing is skipped to keep up; the queue is durable
  and an upsert is idempotent (a rerun changes nothing), so a lost worker loses no frame.
- **Only `ai_workers` touches a model.** `query` sends text to it and gets a vector back; the
  weights, the classifier and the fusion run in `query`.
- **Frame vectors come from two places.** Live and uploaded footage is encoded on this
  laptop's CPU (about 9 s a frame, K-25). The product's 9 VIRAT videos take theirs from the
  Colab archive (cosine 0.99998 or better against the laptop's, OMNI-708). Clip vectors exist
  only for the 9 VIRAT videos: a camera has none (D-32), so a live frame is found by scene only.
- **Search lives where the footage is watched** (D-39): inside the video player and the camera
  viewer, on that footage only. The filter is applied inside both HNSW searches, so a video's
  best match is found even when other footage ranks above it.
- **Fusion** is Algorithm 3 as written (reciprocal rank, `K` = 5), with the classifier's
  weights replaced by fixed ones per kind of query (D-40, a deviation): scene 0.5 / 0.5,
  action 0.6 frame / 0.4 clip. Compare shows the three modes side by side.
- **SM-1 and TC-4 run on the archive, not the laptop.** SM-1 on Colab with the same
  `services/common` code (76.0% against 85%, K-30); TC-4 on the laptop's Qdrant with scratch
  collections (74%, at the archive's 35,704 frames, not 100,000, D-37).
- **Known limits** (`results.md`, `known-issues.md`): action queries are no better than
  frame-only (K-30); the first search after
  an idle waits for the model to load from disk (K-26); one GPU holds about 9 frames a second
  (K-31); a camera keeps frames, not a recording (K-29).
