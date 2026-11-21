# Sync break tests (Milestone 3)

How `ingest/sync.py` behaves when something goes wrong. For each test: what I did, what I predicted
before running it, what happened, and the `sync_runs` row it left. Results come from real output only.

## Test 1: invalid Mouser API key

- **What I did:** ran a manual sync with `MOUSER_API_KEY` set to a fake value in one PowerShell
  session only. `.env` and the GitHub secret were not changed; `load_dotenv` does not override a
  variable that is already set.
  ```
  $env:MOUSER_API_KEY = 'INVALID-TEST-KEY'; .venv\Scripts\python.exe ingest\sync.py --trigger manual
  ```
- **My prediction** (made after seeing run 8): same as run 8: `failed`, 176 calls, about 7 minutes,
  nothing written.
- **What happened** (rerun 2026-11-17, started 05:07:46 UTC): every call came back HTTP 200 with
  Mouser's error "Invalid unique identifier." That message does not contain "key", so `mouser.py`
  raises `BadResponse` (skip the call), not `AccessDenied` (stop the run), and the fail-fast check in
  `sync.py` never fires. All 164 watch batches and the first page of all 12 keywords were skipped:
  176 calls, 0 retries, 176 skipped, 0 parts fetched, 1639 of 1639 watched parts missing, 438 s.
  Status `failed`, exit code 1, nothing written to the parts tables. Run 8 (2026-11-16 08:19 UTC) gave
  the same result.
- **sync_runs row:** run_id 12, `failed`, `manual`, records_fetched 0, inserted 0, updated 0,
  error_message "0 valid parts fetched; 1639 of 1639 watched parts missing; 176 calls skipped after
  errors" (run 8 has the same row).
- **Lesson:** the run fails safely, but it does not fail fast. Mouser rejected the key on the first
  call, yet the run kept going and made 176 calls (about 7 minutes) instead of stopping on that first
  auth error. Fix for later: treat "Invalid unique identifier." as `AccessDenied`.

## Test 2: back-to-back reruns

- **What I did:** ran two manual syncs with the real key, the second right after the first finished.
  ```
  .venv\Scripts\python.exe ingest\sync.py --trigger manual
  ```
- **My prediction:** run 1 succeeds with 0 new parts and a few dozen updated parts plus some price
  break and on-order changes, because about 10 hours passed since the last sync. Run 2 right after
  succeeds with 0 inserted, 0 updated and no child changes, because nothing changed in between.
- **What happened** (2026-11-17, about 10 h 45 min after run 11):
  - **Run 1** (started 07:50:15 UTC, 496 s): `success`, 198 calls, 0 retries, 0 skipped, 1,636 parts
    fetched, 3 watched parts missing. Parts: 0 inserted, 98 updated (21 with a changed value on the
    row, 77 with changed child rows only). Child rows: price breaks 56 inserted, 290 updated, 9 deleted;
    on-order 13 inserted, 1 updated, 13 deleted; attributes 0 changed.
  - **Run 2** (started 07:58:37 UTC, right after run 1 finished, 495 s): `success`, 198 calls,
    0 retries, 0 skipped, 1,636 parts fetched, 3 watched parts missing. Parts: 0 inserted, 0 updated.
    Child rows: 0 price break, on-order or attribute changes.
  - Both runs added 1,644 `part_search_hits` rows. That is expected: each run records which parts each
    keyword returned, stamped with its own start time, so these rows are history, not changed data.
  - Prediction: run 2 held exactly. Run 1 had 0 new parts and price break and on-order changes as
    predicted, but 98 updated parts, more than "a few dozen", and most of them (77) were child-row
    changes only.
- **sync_runs rows:** run_id 13, `success`, `manual`, records_inserted 0, records_updated 98;
  run_id 14, `success`, `manual`, records_inserted 0, records_updated 0.
- **Lesson:** the upsert writes only what changed, so an immediate rerun is a safe no-op: it costs
  198 Mouser calls and about 8 minutes but changes no part data.
- **Earlier attempt:** on 2026-11-16, run 1 was run 9 (`success`, 31 updated) and run 2 became run 10
  (see "Real-world break: network drop" below), which never reached the write step.

## Real-world break: GitHub Actions run #1

- **What happened:** the first Actions run failed because the `DATABASE_URL` secret was malformed.
  `sync.py` could not open the connection it uses for the sync lock and stopped with a psycopg
  `ProgrammingError`, before any Mouser call.
- **sync_runs row:** none. The run never reached the database, so it could not record itself
  (`ingest/sync.py:561-566`: "could not connect to take the sync lock ... No run recorded.").
  The failure shows only in the Actions log.
- **Fix:** I mistyped the secret value when I first added it; I re-entered it carefully and run #2
  succeeded.
- **Lesson:** a run that cannot connect leaves no trace in `sync_runs`, so `scripts/status.py`
  shows it only as stale data once the last success is over 13 hours old, not as a failed run.
  [ANTHONY: confirm, and confirm run #1 used the same connect-for-lock code]

## Real-world break: network drop during a manual sync (run 10)

- **What I did:** this was Test 2's second run, started right after run 9 finished:
  `.venv\Scripts\python.exe ingest\sync.py --trigger manual`.
- **What happened** (from the console log):
  - Watch batches 1–76 were fine. From batch 77, calls failed with `network error (ConnectionError)`;
    batches 77–95 were each retried 3 times and skipped (19 skipped calls). Calls recovered at batch 96,
    with a few more retries at batches 100 and 116, and the watch list finished 164/164 with 1,446 parts.
  - The 63 retries count toward the same call cap as real calls, so after 23 keyword calls the run
    stopped: `STOPPED: reached the 250-call cap`.
  - Elapsed: 18,563 s (about 5 h 9 min). 250 calls with these backoffs take about 25 minutes, so most of
    that time the PC was off the network or asleep. My Wi-Fi dropped during the run, so the connection
    holding the sync lock was lost.
  - The connection holding the sync lock died during that gap. Before writing, `sync.py` checks that it
    still holds the lock (`ingest/sync.py:612-615`); it did not, so it wrote nothing, because another
    sync could have been writing.
- **sync_runs row:** run_id 10, `failed`, `manual`, 2026-11-16 11:59:50 to 17:09:14 UTC,
  records_fetched 1,492, inserted 0, updated 0, error_message "lost the sync lock during the fetch;
  nothing written; stopped early: reached the 250-call cap; 19 calls skipped after errors".
- **Lesson:** the safety checks worked: a partial fetch with a lost lock wrote nothing and left a clear
  `failed` row. The cost was 250 Mouser calls, a quarter of the 1,000 per day, for no data.

## Real-world break: scheduled runs that did not fire on time (Nov 16)

- **What happened:** the schedule was `17 11,23 * * *` (11:17 and 23:17 UTC).
  - **11:17 UTC:** no run at that time. The only scheduled run that day, run 11, started at 21:06 UTC,
    about 9 h 49 min late. [ANTHONY: confirm from the Actions tab whether run 11 was the delayed 11:17 run]
  - **23:17 UTC:** no run and no `sync_runs` row (checked 2026-11-17 04:36 UTC).
- **sync_runs rows:** run 11 only (`success`, `schedule`, 21:06:28 to 21:14:44 UTC). A trigger that never
  fires leaves no row.
- **What I did:** moved the schedule to `41 11,23 * * *` (commit d7b32d5, 2026-11-17 01:33 UTC) to
  re-register the cron. The first :41 run is due at 11:41 UTC on Nov 17. [ANTHONY: record whether it ran]
- **Lesson:** GitHub's schedule is best effort: a run can start hours late or not at all, and nothing alerts
  on a missed run. Only `scripts/status.py` shows it, as stale data, when someone runs it
  (see `docs/data_quality.md`, Alerting).
