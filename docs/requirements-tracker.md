# Requirements tracker

Every requirement, success metric and test case from the Phase A book, where it is tested in
Phase B, and the result. Filled in sprint by sprint as each one is reviewed; an empty row has
not been reviewed yet.

**Status:** Pass · Fail · Partial · Not measured · Not started

## Functional requirements (FR)

| ID | What it says (Phase A) | Where it is tested | Result | Status |
|---|---|---|---|---|
| FR-1a | Accept video from live camera feeds and from uploaded files | Sprint 2: camera test, upload and probe. Sprint 4: live capture (OMNI-312, OMNI-313) | Uploads stored with correct metadata; live: about 4 frames/s stored, stops in 0.1 s, recovers by itself in 11–20 s after the source is killed | **Pass** (sprint 4) |
| FR-1b | Keep the most informative frames by detecting movement | Algorithm 1 on files (OMNI-304, OMNI-305) and live (OMNI-501); retention on 38 dataset clips (OMNI-318) | The gate separates still from moving footage; kept frames: fixed cameras 4.7–19.8%, daylight dash-cam 57%. Live: every frame checked (15/s), 20–22% kept on `cam05`, counters balance | **Pass** on fixed cameras, **weak** on moving cameras (sprint 5) |
| FR-2 | Turn each accepted segment into a searchable representation of what it shows and how it changes | | | |
| FR-3 | Store each analysed segment with its time, source camera and a representative image | `videos` table (sprint 2); `segments` table (OMNI-304, OMNI-316) | A row per frame with time, source, score and reason; image files equal the kept rows in every run | **Pass** (sprint 3–4) |
| FR-4 | Search stored video in plain language, returning a ranked list of the most relevant moments | | | |
| FR-5 | Predict likely upcoming events from recent activity: event type, time until it, confidence | | | |
| FR-6 | Check each predicted event and raise an alert only if it is credible | | | |
| FR-7 | Generate a structured incident report with the evidence, video segments and timeline | | | |
| FR-8 | Let authorised external software use search, analysis, prediction and live alerts | | | |
| FR-9 | Let users search videos, view live alerts and review incident reports | The camera wall (OMNI-503 to 508, 512); the Operations Dashboard and Datasets screen (OMNI-610 to 612) | Wall, tile states, enlarge, rewind, layouts pass. Dashboard counts equal a direct count, every figure links; summary in 41 ms (p50) | **Partial** (sprint 6: live monitoring and dashboard; search and alerts later) |
| FR-10 | Authenticate users before they can use any feature | TC-10 (`services/query/tests/test_tc10_auth.py`); the sign-in page | Sign-in works; protected routes refuse anyone without a valid token (TC-10, 15 of 15) | **Pass** (sprint 1) |

## Non-functional requirements (NFR)

| ID | What it says (Phase A) | Where it is tested | Result | Status |
|---|---|---|---|---|
| NFR-1 | A captured frame is ready to search in under 5 s | First half, capture to stored (OMNI-316, OMNI-502) | Sprint 4: 49 ms alone, 6.14 s with a long file. Sprint 5, live frames on their own queue: max 0.15–0.37 s even with a long upload | **Pass** (first half, sprint 5) |
| NFR-2 | Search results appear in under 3 s | | | |
| NFR-3 | A forecast is ready in under 2 s | | | |
| NFR-4 | Handle at least 10 live feeds at once without slowing down | OMNI-317 (preliminary); OMNI-509, OMNI-510a, the NFR-4 revision (D-19); OMNI-613 | Sprint 4: 8 sustained. Sprint 5, every frame checked, real footage, wall open: 3 sustained for 10 min; 4 not; 10 not, on a 4-core laptop. Sprint 6: faster grid calculation, identical results, still 3 | **Fail** against Phase A (10); **Pass** against the revised target (3 per machine of this class, D-19) |
| NFR-5 | Data lost when any part fails or crashes = 0 | Sprint 2: uploads. Sprint 3–4: OMNI-311, OMNI-319. Sprint 6: OMNI-601 (live, rechecked) | Uploads: 3 of 3. Frames: consumer killed, broker rebuilt (1,800 of 1,800 kept), ingestion restarted and killed: 0 lost. Rechecked for live on the sprint 5 pipeline: 0 lost, 32 of 32 checks, 2 runs | **Pass** in the cases tested (sprint 6) |
| NFR-6a | Each major part can be updated or replaced on its own | | | |
| NFR-6b | New prediction types can be added without changing existing parts | | | |
| NFR-7 | 100% of API endpoints and MCP tools reject requests without a valid token or role | TC-10 suite; role checks on the camera and video routes | All 4 protected routes refused a missing, expired or tampered token (401); the one admin-only route (`/admin/ping`) refused the wrong role (403). Sprint 2: camera writes are admin-only, the operator gets 403 (demo step 5) | **Pass** (sprints 1–2: the routes that existed then) |
| NFR-8 | 100% of traffic encrypted with TLS 1.2+; plaintext bytes = 0 | Built: nginx with TLS 1.2 and 1.3 only, plain HTTP redirects to HTTPS | Not recorded in `results.md` | **Not measured** |
| NFR-9 | Tokens expire after at most 15 min idle; account locks after 5 failed logins | `services/query/tests/test_nfr9_lockout_expiry.py` | 2 of 2: 5 wrong passwords lock the account (the correct password is then refused too); an expired token is refused | **Pass** (sprint 1) |

## Success metrics (SM)

| ID | What it says (Phase A) | Where it is tested | Result | Status |
|---|---|---|---|---|
| SM-1 | Search quality: the right clip in the top 5 for at least 85% of queries, with a lift on action queries over frames only (VIRAT) | | | |
| SM-2 | Prediction accuracy: the real event in the top 3 predictions in at least 70% of cases, per domain | | | |
| SM-3 | Early warning: warnings at least 15 s before the event (Phase A: on DoTA) | Revised (D-2): mean time-to-accident on CCD; target rule D-23 (OMNI-606) | Target **≥ 1.80 s**: half the held-out median pre-crash footage (3.60 s); written before measuring. No model yet | **Target set, not measured** (sprint 6) |
| SM-4 | False alarms: at most 20% of warnings false, per domain (UCF-Crime) | | | |
| SM-5 | Cross-domain learning: pre-training on two domains lifts the third by at least 10% | | | |
| SM-6 | Forensic reports: a structured report for at least 2 multi-camera scenarios (AI City) | | | |

## Test cases (TC)

| ID | What it checks (Phase A) | Where it is tested | Result | Status |
|---|---|---|---|---|
| TC-1 | A live feed and an uploaded file at once; only frames with motion forwarded (FR-1a, FR-1b) | OMNI-316 (first half); OMNI-511 (complete, on the wall) | 2 runs, 15 of 15 checks each: 0 decode errors, 0 violations, the camera Live throughout | **Pass, complete** (sprint 5) |
| TC-2 | A frame and a clip embedding for each admitted segment (FR-2) | | | |
| TC-3 | Each embedding stored in Qdrant with its metadata intact (FR-3) | | | |
| TC-4 | Plain-language search over at least 100,000 embeddings; right clip in the top 5 for 85% (FR-4) | | | |
| TC-5 | Predict early and accurately, bounded false alarms, transfer to an unseen domain (FR-5) | | | |
| TC-6 | Four-tier verification suppresses benign clips and lowers false positives (FR-6) | | | |
| TC-7 | An evidence-grounded report from multiple cameras after an operator confirms (FR-7) | | | |
| TC-8 | All capabilities reachable by external AI agents through MCP, including live alerts (FR-8) | | | |
| TC-9 | The search, alerts and report views render without errors (FR-9) | | | |
| TC-10 | Every endpoint protected by authentication and roles: right role 200, wrong role 403, no or bad token 401 (FR-10) | `services/query/tests/test_tc10_auth.py` | 15 of 15 on the 4 protected routes (`/auth/me`, `/nav`, `/auth/logout`, `/admin/ping`); MCP tools do not exist yet | **Pass** (sprint 1) |
