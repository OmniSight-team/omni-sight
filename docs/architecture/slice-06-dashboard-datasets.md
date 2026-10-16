# Slice 6 · Real footage, and the dashboard comes alive

The three datasets become labelled data the forecasting slices can train on: every clip
listed by a loader, split once, its lead-up windows derived from annotations and exported,
a sample of them checked by eye. The hand-check sample enters the product as ordinary
footage, through the same function as an upload. Over everything, an Operations Dashboard
whose every figure leads to its screen, kept fast by an hourly rollup. Built in OMNI-600 to
OMNI-613.

```mermaid
flowchart LR
    DRIVE[("Google Drive<br/>full UCF-Crime, CCD, VIRAT")]
    MIRROR[/"data/ (local mirror, never committed)<br/>annotations + video_files.txt + video_probe.csv<br/>the 60 sampled clips"/]

    subgraph common["services/common · omnisight_common.datasets"]
        LOAD["three loaders<br/>ucf_crime (official + UCA times, D-21)<br/>ccd (binlabels) · virat<br/>native layout, no guesses"]
        SPLIT["split.py<br/>train / validation / held-out<br/>group-aware (CCD source video)"]
        WIN["windows.py<br/>backward from each event start<br/>positive + negative, L = 30 s, 60 s<br/>no event time → no window (D-24)"]
        HC["hand_check.py<br/>60-clip sample"]
    end

    subgraph files["datasets/ (committed, hashed, fixed once)"]
        SCSV[/"splits/{dataset}.csv"/]
        WCSV[/"windows/{dataset}.csv<br/>+ _skipped.csv with reasons"/]
        HCSV[/"hand_check/sample.csv"/]
    end

    COLAB["Colab GPU (D-26)<br/>SM-1 to SM-4 later<br/>reads the same CSVs from Drive"]

    subgraph query["services/query"]
        DL["POST /datasets/{name}/load<br/>admin, one clip at a time"]
        SV["store_video()<br/>the body of POST /videos/upload (D-25)<br/>source = dataset, never expires"]
        EX["extraction: Algorithm 1<br/>every frame gated"]
        DS["GET /datasets<br/>clips, windows derived / checked / verified,<br/>load progress"]
        WS["GET /windows · /windows/{id}<br/>POST /windows/{id}/verdict"]
        DASH["GET /dashboard/summary · /activity<br/>read the rollup, not count(*)"]
        DB[("PostgreSQL<br/>dataset_manifest (split, video_id)<br/>event_windows (+ verdicts)<br/>videos · segments<br/>segment_hourly, kept by triggers (D-28)")]
    end

    subgraph browser["Browser"]
        OD["Operations Dashboard<br/>cameras · footage · segments · storage · datasets<br/>activity · every figure links, 30 s refresh"]
        DSP["Datasets screen<br/>Load N with progress"]
        WP["Windows · check screen<br/>the clip played over the window,<br/>Correct / Wrong (D-27)"]
    end

    DRIVE -->|"list_dataset_videos.py,<br/>probe_dataset_videos.py"| MIRROR
    MIRROR --> LOAD
    LOAD -->|"build_dataset_manifest.py"| DB
    LOAD --> SPLIT -->|"build_dataset_split.py"| SCSV
    SCSV --> WIN
    LOAD --> WIN -->|"build_event_windows.py"| WCSV
    WCSV --> DB
    WCSV --> HC -->|"build_hand_check_sample.py"| HCSV
    SCSV --> COLAB
    WCSV --> COLAB
    HCSV --> DL
    MIRROR -.clips, read-only.-> DL
    DL --> SV --> EX --> DB
    DSP --> DL
    DSP --> DS --> DB
    WP --> WS --> DB
    OD --> DASH --> DB
    OD -.links.-> DSP
```

## What to know when reading it

- **Every window comes from an annotation.** UCF-Crime's test videos use the official times,
  its training videos UCA's, picked by a written rule (D-21); CCD its first accident frame.
  An event with no time gets no window, and the reason is written to `_skipped.csv` (D-24).
- **The split comes first and never moves** (D-22). Windows take their clip's split; CCD
  clips from one YouTube video stay on one side. Rebuilding the split, the windows or the
  sample must give identical bytes, or the script stops and writes nothing.
- **Dataset footage is ordinary footage** (D-25). The load endpoint loops over
  `store_video()`, the same function as an upload, then extracts with the same gate. Only
  `source = dataset` and no retention date differ.
- **The product holds only the hand-check sample** (D-26): 60 clips, 30 per dataset. The
  model measurements run on Colab's GPU from Drive with the same `services/common` code and
  the committed CSVs; the full datasets never enter the product.
- **The dashboard reads a rollup.** Triggers on `segments` keep `segment_hourly` exact in
  the same transaction as each insert or delete (D-28), so the summary does not count
  146,807 rows on every refresh.
- **The SM-3 target is set** from CCD's held-out pre-event footage by a rule written first
  (D-23): mTTA ≥ 1.80 s.
- **Known limits** (`results.md`, `known-issues.md`): UCA-timed windows are wrong twice as
  often as official ones (K-20, before slice 9 trains); about 1 GB of files on disk have no
  row and are not in the storage figure (K-21); the gate still reads camera motion as scene
  motion (K-4, slice 7); NFR-4 stays at 3 live feeds per machine after the one-operation grid
  (D-19, OMNI-613).
