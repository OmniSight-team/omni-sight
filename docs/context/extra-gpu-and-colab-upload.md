# Extra — Uploads fully searchable: GPU by itself, laptop through Colab

## OMNI-X05 · Any video through Colab and Drive, the VIRAT way

### Why this ticket exists

An upload gets scene vectors only, slowly, on the laptop's CPU; action vectors exist only for the 9 VIRAT videos
(D-32). Colab already makes both for VIRAT (OMNI-708). This makes it work for any video.

### What was done

- **Fingerprint (D-47):** `videos.fingerprint`, the SHA-256 of the file, hashed in `store_video` as the bytes stream
  to disk (no second read), so uploads and dataset clips both get it. Migration `b7e2c94d1f06` also adds
  `videos.colab_vectors` (this extraction's vectors come from Drive: the consumer queues no CPU embed job)
- **Colab side:** `scripts/encode_uploads.py` wraps `encode_virat_archive.encode_video` (same gate, same encoders, same
  windows) and writes `ready/{fingerprint}/` = the video, `vectors.npz`, `info.json` (file name, pins, gate settings,
  counts). Built as `{fingerprint}.part/` and renamed when complete; a finished folder with the same pins and settings
  is skipped, one with others refused. `notebooks/encode_upload_gpu.ipynb` runs it (clones branch
  `gpu-and-colab-upload`)
- **Ingestion:** `GET /extraction-settings`, the nine settings that decide which frames are kept and how their JPEGs
  look, under the same names Colab writes, so query compares one for one
- **Query:** `app/colab_vectors.py`. `run_extraction(..., ready)`: before ingestion publishes, `prepare` refuses other
  pins or settings and sets `colab_vectors`; after every segment is stored, `finish` matches every admitted frame to a
  row (index, time, reason) and every row to a frame, then upserts both vectors by segment id. Any mismatch or error:
  nothing imported, the reason logged, the frames queued for the CPU (`fall_back`), so a video never ends with no
  vectors. A point of the pinned model that is already there is left alone. `add_ready(folder)` stores a new video and
  extracts it with its vectors, or, for a file already in the system (same fingerprint, any name), extracts it with the
  vectors if it never was, otherwise imports them
- **`scripts/add_from_drive.py`** on the host: lists `G:/My Drive/omnisight/ready/` with each video's state
  (new / in the system, scene x/n, action x/n), and adds `<numbers>`, `all` or a fingerprint start: `docker compose cp`
  the folder into `query`, then `add_ready` there, as the VIRAT imports do
- **Ticket changed twice while building (Ahmad):** first the Drive folder was to be mounted into query. It cannot be:
  Docker Desktop does not see Google Drive for desktop's `G:` drive (a `docker run -v "G:/My Drive/...":/x` showed an
  empty folder, while the same files are readable from Windows). Then the ticket moved to the ready-folder layout and an
  "Add from Drive" button, and finally to a host script like the VIRAT import, with no button. The earlier mount, `.env`
  setting and `import_upload_vectors.py` were removed

### Verification performed

- `scripts/tests/test_encode_uploads.py` (5): the folder is named by the SHA-256 and holds the video, vectors and
  info; a renamed copy is skipped (same fingerprint); other pins or settings refused, nothing overwritten; an
  unfinished folder is redone; the streamed hash equals the plain SHA-256
- `services/query/tests/test_colab_vectors.py` (13): a new video gets both vectors by frame and no CPU job; adding twice
  changes nothing and makes no second video; a normal upload (renamed) then added gets the Drive vectors; a video not
  on Drive goes to the CPU; other pins refused; other settings refused for a video already in; a frame mismatch
  imports nothing and falls back; a wrong video file in the folder is refused; status; the match and settings checks
- Related suites: 355 passed (query extraction, consumer, upload, embeddings, dataset load, gate; ingestion; scripts)
- **On the real stack** (stand-in vectors, no GPU here): two CCD clips (`Crash-1500/000026`, `000086`) made ready with
  `encode_uploads` on the laptop (random unit vectors, the real gate), in a scratch folder (not Drive). `000086` first
  uploaded normally as `x05-uploaded-normally.mp4` (CPU path, 12 frames, 0 action vectors). Then `add_from_drive.py
  all`: `000026` added, 40 of 40 frames matched, scene 40, action 40; `000086` "existing", the uploaded video got
  12 + 12. Running `all` again chose nothing; `1 2` again: same videos, same counts, no second row per fingerprint.
  Copying a folder from `G:` into `query` with `docker compose cp` works (checked with `omnisight/results`). The test
  videos and their points were deleted afterwards; the embed queue and its dead letters were empty

### Not verified

- The notebook has not run on Colab yet, so no real vectors and no search by scene and action on an added video. The
  branch must be pushed first (the notebook clones it)
- Re-gating a video (OMNI-306) after its vectors were imported does not refresh them; the same holds for CPU vectors
  today
- A file uploaded normally while its CPU jobs are still queued, then added from Drive: the CPU jobs still run and
  overwrite those frame vectors with the CPU's (same model, so search is unaffected)

### Result

Code done and tested; the Check section's Colab run is Ahmad's next step.
