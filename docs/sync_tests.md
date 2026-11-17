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
- **My prediction:** [ANTHONY: fill in before running]
- **What happened:** [from the console: status, calls made, skipped calls, reasons, elapsed]
- **sync_runs row:** [run_id, status, records_fetched, error_message]

## Test 2: back-to-back reruns

- **What I did:** ran two manual syncs with the real key, the second right after the first finished.
  ```
  .venv\Scripts\python.exe ingest\sync.py --trigger manual
  ```
- **My prediction:** [ANTHONY: fill in before running]
- **What happened:** [run 1: parts inserted / updated, child rows changed; run 2: the same counts]
- **sync_runs rows:** [both run_ids, status, records_inserted, records_updated]
- **Status:** run 1 was run 9. Run 2 became run 10 (see "Real-world break: network drop" below) and
  never reached the write step, so back-to-back behavior is not yet tested.

## Real-world break: GitHub Actions run #1

- **What happened:** the first Actions run failed because the `DATABASE_URL` secret was malformed.
  `sync.py` could not open the connection it uses for the sync lock and stopped with a psycopg
  `ProgrammingError`, before any Mouser call.
- **sync_runs row:** none. The run never reached the database, so it could not record itself
  (`ingest/sync.py:561-566`: "could not connect to take the sync lock ... No run recorded.").
  The failure shows only in the Actions log.
- **Fix:** [ANTHONY: how you corrected the secret]
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
    that time the PC was off the network or asleep. [ANTHONY: confirm what happened to the PC]
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
