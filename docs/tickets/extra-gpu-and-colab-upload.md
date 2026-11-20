# Extra — Uploads fully searchable: on a GPU by themselves, on the laptop through Colab

**Not a slice · branch `gpu-and-colab-upload`**
Board: OmniSight Phase B · Assignee: Ahmad

> **When it is done:** add any video (a dataset clip or a random file) and it ends up with
> **both** vectors, scene and action, and search finds it. On a machine with a GPU the system
> does it by itself; on the laptop, Colab prepares the video and its vectors on Drive and the
> system adds both from there.

**Why:** today an upload gets scene vectors only, slowly, on the laptop's CPU, and action
vectors exist only for the 9 VIRAT videos, made by hand on Colab (D-32). We want any video to
be fully searchable now, and the real product path (upload → done, no Colab) ready for the
Google Cloud GPU machine.

**Not in this ticket:** creating the Google Cloud machine; live cameras on the GPU (later);
training any model; an "Add from Drive" button in the UI (a script for now, like the VIRAT import).

---

## OMNI-X04 · ai-workers uses a GPU when there is one

- [ ] At start, ai-workers checks for a GPU (`torch.cuda.is_available()`) and logs which one
      it uses. **GPU found:** all models run on it. **No GPU:** everything runs on the CPU, as today
- [ ] **On a GPU, the action side is loaded too.** InternVideo2's video encoder runs inside the
      system, and every kept frame gets its action vector exactly as Colab makes it today:
      the same window, the same 8 frames, the same model pin (D-33). On the CPU, nothing
      changes: scene vectors only (D-32)
- [ ] A GPU build of the ai-workers image (CUDA PyTorch). The laptop keeps the CPU build; the
      same code runs in both
- [ ] A separate compose file, `docker-compose.gpu.yml`, that gives ai-workers the GPU:
      `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`. The laptop's
      command does not change
- [ ] `/health` says `cpu` or `gpu` and which vectors this machine makes, so the screen's
      "searchable so far" line is honest
- [ ] **D-46:** D-32 now applies only to machines without a GPU

## OMNI-X05 · Any video through Colab and Drive, the VIRAT way

The same idea as the VIRAT import (OMNI-708, `match_product`): the same video, gated by the same
code with the same settings, keeps the same frames, so vectors made on Colab match the system's
frames by frame index. What is new: it works for **any** video, not only VIRAT.

- [x] **A video's fingerprint:** the SHA-256 of the file. Stored on the `videos` row. It names
      the video's folder on Drive and proves the system's copy is the same file Colab encoded.
      **D-47**
- [ ] **A Colab notebook** (`notebooks/encode_upload_gpu.ipynb`), reusing
      `encode_virat_archive.py`'s code: pick videos (from a dataset folder on Drive or any file
      uploaded to Colab), run Algorithm 1 and both encoders, and save each one to
      `Drive/omnisight/ready/{fingerprint}/`: the **video file itself**, `vectors.npz` (frame
      index, time, scene vector, action vector) and `info.json` (original file name, model pins,
      gate settings)
- [x] **`scripts/add_from_drive.py`, run on the host** (like the VIRAT imports; Docker Desktop
      cannot see Google Drive's `G:`, so nothing is mounted): reads `G:/My Drive/omnisight/ready/`
      and lists the ready videos (name, length, frames kept, "scene + action ready", and whether
      each is already in the system). For the ones chosen (`<numbers>` or `all`) it copies the
      folder into `query`, stores the video as an upload is, extracts its frames with the same
      gate, and imports both vectors by frame index (as `import_frame_vectors.py` and
      `import_clip_vectors.py` do). No upload, no CPU encode
- [x] A file that is already in the system (uploaded normally, under any name: same
      fingerprint) is not added twice: the script gives that video the Drive vectors. A normal
      upload of a file that is not on Drive is encoded on the CPU as today
- [x] Refuse a folder made with other model pins or other gate settings; never mix them in
- [x] Every frame must match. If some don't, report how many and import nothing for that video
      (its frames then go to the CPU encode)
- [x] Adding the same video twice changes nothing

## Check

- [ ] **On the laptop:** a short random video (about 1 min) encoded on Colab, then added with
      `scripts/add_from_drive.py`. Both vectors appear, every frame matched, and search finds it
      by scene and by action
- [ ] **The same file uploaded normally first** (even renamed), then added from Drive: no second
      video; the uploaded one gets the Drive vectors (the fingerprint)
- [ ] **A video not on Drive:** uploaded normally, falls back to the CPU encode, nothing breaks
- [ ] **The GPU path** (run when the Google Cloud machine exists): the same video uploaded
      there gets both vectors by itself; record seconds per frame and compare its vectors
      with Colab's (cosine ≥ 0.999)
- [ ] Results in `docs/results.md`; D-46 and D-47 in `docs/decisions.md`; README: how to run
      with a GPU
