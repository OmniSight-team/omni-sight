# Extra — Share the system's data with Cyrine

**Not a slice · Nov 2026 · branch `share-data`**
Board: OmniSight Phase B · Assignee: Ahmad

> **When it is done:** Ahmad runs one command and gets a backup folder; he puts it on Google
> Drive; Cyrine downloads it, runs one command, and her system shows the same videos, frames,
> cameras, dashboard and search results as Ahmad's.

---

## OMNI-X01 · Backup and restore of the whole system's data

**Why:** Cyrine is joining. A fresh clone starts empty: the videos, the database rows and the
vectors exist only on Ahmad's laptop, and rebuilding them (dataset loads, Colab imports, the
9 s per frame encoding) would take hours.

**What is copied:** every named volume that holds data, so the copy is exact:
`postgres_data`, `qdrant_data`, `video_storage`, `frame_storage`, `thumb_storage`.
**Not copied:** `rabbitmq_data` (queues are drained first), `preview_storage` (rebuilt by live
cameras), `frontend_node_modules` (rebuilt), the model weights in `models/pretrained/` (each
machine downloads them at the pinned revision, D-30, D-33).

### Backup: `scripts/backup_data.py <out-folder>`

- [ ] Refuses to start if any embed or segment queue still holds messages (nothing in flight
      is lost); asks to stop the stack with `docker compose stop`, never `down -v`
- [ ] **Cold copy:** with the stack stopped, each volume is written to one `.tar.gz` by a
      throwaway container (`docker run --rm -v <volume>:/data ...`), so Postgres and Qdrant
      files are consistent
- [ ] Volume names are found from the compose project (`docker compose config` and the
      project name), not hard-coded, because the project name is the folder name and
      Cyrine's folder may differ
- [ ] `manifest.json` beside the archives: git commit, date, Postgres and Qdrant image
      versions, each archive's size and SHA-256, and the counts to check against: videos,
      segments, cameras, users, `frame_vectors` points, `clip_vectors` points
- [ ] Prints the folder size and the time taken; the stack is started again at the end

### Restore: `scripts/restore_data.py <backup-folder>`

- [ ] Checks every archive's SHA-256 against the manifest before touching anything
- [ ] Refuses if the Postgres or Qdrant version in `docker-compose.yml` differs from the
      manifest's
- [ ] Refuses if the target volumes already hold data, unless `--replace` is given (so
      nobody wipes their own work by mistake)
- [ ] Creates the volumes under **this** machine's compose project name and unpacks each
      archive into its volume
- [ ] Starts the stack and checks the counts in `manifest.json`: all equal, or a clear list
      of what differs

### The rest

- [ ] **`.env`:** the database password lives inside `postgres_data`, so Cyrine needs the
      same `.env` as Ahmad. It is sent privately, never committed; the restore script says so
      if login to Postgres fails
- [ ] `docs/sharing-data.md`: the steps for both people in plain English, including how much
      space it needs and how long it takes
- [ ] A test on this laptop: backup, restore into a second compose project
      (`docker compose -p omnisight-restore-test`), counts equal, then that project removed
- [ ] Measure and record in `results.md`: backup size, backup time, restore time

**Acceptance:** a backup made on Ahmad's laptop, restored into a second project, gives equal
counts for every table and collection and the same top 5 for one search; the steps are in
`docs/sharing-data.md`.

---

## Working with Claude Code

`CLAUDE.md` is read automatically. Paste the ticket, then:

> Here is ticket OMNI-X01 from our sprint board. Implement exactly what it asks and nothing
> more. When you are done, show me the diff, tell me which acceptance criteria you verified
> and how, and suggest a short commit message without the ticket number. Do not run any git
> command that changes the repository; I commit myself.

**You create the branch first:** `git switch -c share-data`.
