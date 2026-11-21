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
  Run #1 ran `main` at eb61dad, which has the same connect-for-lock code.

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
    about 9 h 49 min late. It was Actions run #3 (scheduled), the delayed 11:17 trigger.
  - **23:17 UTC:** no run and no `sync_runs` row (checked 2026-11-17 04:36 UTC).
- **sync_runs rows:** run 11 only (`success`, `schedule`, 21:06:28 to 21:14:44 UTC). A trigger that never
  fires leaves no row.
- **What I did:** moved the schedule to `41 11,23 * * *` (commit d7b32d5, 2026-11-17 01:33 UTC) to
  re-register the cron. The :41 schedule ran late but ran: Actions run #4 at 2026-11-17 19:59 UTC
  (about 8 h late) and #5 at 2026-11-18 04:41 UTC (about 5 h late), both success. That makes three
  scheduled successes within 48 hours.
- **Lesson:** GitHub's schedule is best effort: a run can start hours late or not at all, and nothing alerts
  on a missed run. Only `scripts/status.py` shows it, as stale data, when someone runs it
  (see `docs/data_quality.md`, Alerting).

## Golden check rerun (Nov 21)

- **What I did:** reran the golden reference check (connects with `APP_DATABASE_URL` only) and compared it
  with the Nov 16 baseline:
  ```
  python evals/check_reference.py
  python evals/check_reference.py --diff evals/results/20261116T081646Z.json evals/results/20261121T202430Z.json
  ```
  The result files stay local (`evals/results/*.json` is gitignored because it holds Mouser part data).
- **Baseline:** 2026-11-16 08:16 UTC (`20261116T081646Z.json`). The last successful sync then finished at
  01:37 UTC (Actions run #2).
- **Rerun:** 2026-11-21 20:24 UTC (`20261121T202430Z.json`): 13 queries run, 13 ok and non-empty, 5 skipped
  (decline by design), exit code 0.
- **Scheduled Actions runs in between:** ten, all `success`. Every :41 run started late: the 11:41 runs at
  19:14–19:59 UTC, the 23:41 runs at 04:14–04:41 UTC.

  | Actions run | Started (UTC) | sync_runs run_id | Parts inserted | Parts updated |
  |---|---|---|---|---|
  | #3 | 2026-11-16 21:06 | 11 | 0 | 54 |
  | #4 | 2026-11-17 19:59 | 15 | 18 | 95 |
  | #5 | 2026-11-18 04:41 | 16 | 0 | 39 |
  | #6 | 2026-11-18 19:34 | 17 | 6 | 52 |
  | #7 | 2026-11-19 04:29 | 18 | 0 | 82 |
  | #8 | 2026-11-19 19:37 | 19 | 22 | 88 |
  | #9 | 2026-11-20 04:14 | 20 | 0 | 113 |
  | #10 | 2026-11-20 19:14 | 21 | 6 | 57 |
  | #11 | 2026-11-21 04:15 | 22 | 0 | 37 |
  | #12 | 2026-11-21 18:11 | 23 | 12 | 59 |

  Manual runs 8–14 (Tests 1 and 2 above) also fell in this window; they inserted no parts. The scheduled
  runs inserted 64 parts, which matches GQ16's part count going from 1,639 to 1,703.
- **Diff result:** 9 of 18 questions changed. GQ05, GQ07, GQ08, GQ09 and the five decline questions were
  the same.

  | Question | Nov 16 | Nov 21 | Why |
  |---|---|---|---|
  | GQ01 in-stock 20 A PDUs | Tripp Lite PDUMV20HV lead time 80 days | 85 days | Same 18 parts; Mouser changed one lead time. |
  | GQ02 power strips with an amp rating | 20 A: 35 parts; not stated: 212 (117 in stock) | 20 A: 39; not stated: 229 (116 in stock); other shares down 0.1–0.3 points | 21 more power strips: 4 at 20 A, 17 with no rating. |
  | GQ03 rack widths | Lead time 0 on five L-Com 23" racks, 122 on LC23IN4P42U-S, 0 on StarTech WALLSHELF4U | 80 days on all six L-Com racks, 29 on WALLSHELF4U | Same 18 parts; Mouser changed 7 lead times. |
  | GQ04 commodity cables | AC cords 160 (125 in stock, 5 of 35 out of stock with an ETA); Ethernet 377 (304, 17 of 73); fiber 176 (174, 0 of 2) | AC cords 168 (129, 10 of 39); Ethernet 403 (343, 4 of 60); fiber 179 (175, 1 of 4) | New parts in all three categories plus stock changes; Ethernet in stock rose by 39. |
  | GQ06 SFPs seen in the last 7 days | 150 rows | 154 rows: 5 added (StarTech GLCLXSMRGDST, Molex 183702-1000, Amphenol ProLabs FTLF8519P2BNL-C, SFP-GD-BX34-C, SFP-10G-SR-S-C), 1 dropped (Amphenol ProLabs GLC-T-C), 14 stock and 8 lead time changes | The query keeps SFPs the "sfp transceiver" search returned in the last 7 days; that window now holds 5 SFPs it didn't on Nov 16 and no longer holds GLC-T-C. `run_started_at` on all 149 kept rows moved to the 2026-11-21 18:12 run. |
  | GQ10 25G SFPs | Amphenol ProLabs SFP-10/25G-LR-S-C lead time 0; Coherent FTLF8536P5BCV 80 in stock | Lead time 28; 0 in stock | Same 11 parts; Mouser changed one lead time and one stock level. |
  | GQ11 price after tariffs | 11%: 68 parts, highest $504.28 ($559.75 with tariff); 32%: 4 parts, lowest $6.40 ($8.45) | 11%: 69 parts, highest $3,126.23 ($3,470.12); 32%: 5 parts, lowest $6.22 ($8.21); 15%, 38% and 8% gained 1, 2 and 2 parts | New Eaton EVMAG332X power strip (first seen 2026-11-17 20:08 UTC, run 15) is the new 11% high. |
  | GQ12 out-of-stock wait | 488 out of stock; lead time stated 166, not stated 322; average 72 days; 63 with an on-order date | 508; 184, 324; 65 days; 72 | 20 more parts out of stock, and more of them have a stated lead time or an on-order date. |
  | GQ16 in stock now | 1,151 of 1,639 in stock; last successful sync 2026-11-16 01:37 UTC, 6 h 39 min old | 1,195 of 1,703; 2026-11-21 18:20 UTC, 2 h 4 min old | 64 new parts from the scheduled runs; the sync age is measured from Actions run #12. |

- **Lesson:** no question broke: all 13 queries still run and return rows, and every change I traced is in
  the part data (new parts, stock and lead time updates, and GQ06's 7-day window). The saved answers are a
  snapshot, so an exact match between days is not expected. The result files do not record the SQL they
  ran, so this diff cannot show whether a reference query itself changed.
