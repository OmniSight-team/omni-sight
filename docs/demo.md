# Demo: search, five minutes (slices 7 and 8)

For the supervisor. Start on a fresh stack: `docker compose up -d`, open **https://localhost**
(not port 3000: playback only works through nginx) and sign in. All 9 VIRAT videos have both
scene and action vectors. Allow the first search a few seconds: after an idle the text model
loads from disk (K-26).

## 1. A scene query (1 min)

Videos, open any VIRAT video, type **a blue car**, press Search (Combined is the default).
Expect: five thumbnails with their time, a badge (Scene, Action or Scene + action), a score, and
the time taken (well under 3 s). Click a hit: the player jumps to that second. Scene finds
small, far objects too. This is the strong side: scene queries found the right footage for
92% of the 25 test queries.

## 2. An action query, and where it fails (1 min)

Open video **3231** (`VIRAT_S_040103_00_000000_000120`), click **Compare**, type **a person
unloading an object from a car**.
Expect: Scene and Combined put four of five hits between 104 and 111 s, where a person takes a
pink bag from an open trunk (102 to 110 s, left of the frame). Action's hits (1, 2, 15, 16, 27 s)
miss. Click a Scene hit at about 109 s to see it in the player. Say it plainly: action search
is no better than scene search yet (60% against 60% on the 25 action queries).

## 3. Playback from any hit (30 s)

Click any result: the player seeks to that second. (A live camera's result opens its stored
frame instead: a camera keeps frames, not a recording, K-29.)

## 4. The numbers (2 min)

| Requirement | Target | Measured | Result |
|---|---|---|---|
| NFR-2, results in under 3 s | 3 s | max 2.02 s on this laptop's CPU, 217 ms with a GPU text encode (1,800 requests) | Pass |
| NFR-1, capture to searchable | 5 s | 3.35 s with the GPU's encode time; 270 s on this laptop's CPU | Pass on the combined figure (D-31) |
| SM-1, recall@5 on 50 labelled queries | 85%, with a lift on actions | 76.0% fused, 74.0% frame only; action 60% against 60% | Fail (K-30) |
| TC-4, the same queries over 35,704 frames | 85%, every query under 3 s | 74% fused; search at most 0.2 s; one cold first query 10.9 s | Fail (D-37, K-26) |

Where to see them: `docs/results.md`; the SM-1 figures are what `GET /metrics/sm1` serves. Be ready
to say why SM-1 fails, from what was measured: the clip list adds nothing on action queries
(K-30); 12 of the 50 queries are found by no mode; and the 85% target was our own choice in
Phase A. D-40 records the weights we chose to improve it; the models were not changed.

## If something goes wrong

- *The search model is unavailable:* `ai_workers` is still loading; wait a minute.
- First search slow (up to about 10 s): K-26, repeat it.
- Scene column empty: the video has no scene vectors; every VIRAT product video should have
  them (K-27 fixed). Uploaded or live footage is encoded at about 9 s a frame on this
  CPU, so it fills in slowly: the "searchable so far" line shows how far.
