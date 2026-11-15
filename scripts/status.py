"""Week 3 sync status: how fresh is the data, and how much has the sync changed lately?

Run it from the project folder:

    python scripts/status.py

It connects with APP_DATABASE_URL only (the read-only app_reader role), runs SELECTs only, and
never prints the connection string. Exit code 0 means the last successful sync is within the
freshness limit; 1 means the data is stale or no sync has ever succeeded.
"""

import os
import sys
from datetime import timedelta

import psycopg
from dotenv import load_dotenv

FRESHNESS_LIMIT = timedelta(hours=13)  # 12-hour schedule plus 1 hour of slack
WINDOW = "7 days"

LAST_SUCCESS = """
    select run_id, finished_at, now() - finished_at, trigger
    from sync_runs where status = 'success'
    order by finished_at desc limit 1
"""
LATEST_RUN = """
    select run_id, finished_at, status, error_message
    from sync_runs order by finished_at desc limit 1
"""
TOTALS = f"""
    select count(*),
           count(*) filter (where status = 'success'),
           count(*) filter (where status = 'partial'),
           count(*) filter (where status = 'failed'),
           coalesce(sum(records_inserted), 0),
           coalesce(sum(records_updated), 0)
    from sync_runs where finished_at >= now() - interval '{WINDOW}'
"""
CROSS_CHECK = f"""
    select count(*) filter (where first_seen_at >= now() - interval '{WINDOW}'),
           count(*) filter (where last_updated_at >= now() - interval '{WINDOW}')
    from parts
"""


def age(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min ago"
    return f"{hours // 24} days ago"


def main():
    load_dotenv()
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        print("[FAIL] APP_DATABASE_URL is not set.")
        sys.exit(1)

    try:
        with psycopg.connect(url, connect_timeout=10) as conn:
            now = conn.execute("select now()").fetchone()[0]
            last = conn.execute(LAST_SUCCESS).fetchone()
            latest = conn.execute(LATEST_RUN).fetchone()
            runs, ok, partial, failed, inserted, updated = conn.execute(TOTALS).fetchone()
            first_seen, last_updated = conn.execute(CROSS_CHECK).fetchone()
    except psycopg.Error as error:
        print(f"[FAIL] {type(error).__name__}: {str(error).strip().splitlines()[0]}")
        sys.exit(1)

    print(f"Sync status (as of {now:%Y-%m-%d %H:%M} UTC)")
    if last:
        run_id, finished, delta, trigger = last
        print(f"  Last successful sync:   run {run_id}, finished {finished:%Y-%m-%d %H:%M} UTC "
              f"({age(delta)}), trigger {trigger}")
        fresh = delta <= FRESHNESS_LIMIT
    else:
        print("  Last successful sync:   none yet")
        fresh = False
    if latest:
        run_id, finished, status, message = latest
        line = f"  Latest run of any kind: run {run_id}, {status}"
        if status != "success" and message:
            line += f" ({message})"
        print(line)
    limit_hours = int(FRESHNESS_LIMIT.total_seconds() // 3600)
    print(f"  Freshness:              {'OK' if fresh else 'STALE'} (limit {limit_hours} h)")

    print()
    print(f"Last {WINDOW} (from sync_runs):")
    print(f"  runs:      {runs} ({ok} success, {partial} partial, {failed} failed)")
    print(f"  inserted:  {inserted} parts")
    print(f"  updated:   {updated} parts")
    print()
    print(f"Cross-check (from the parts table, last {WINDOW}):")
    print(f"  first seen:    {first_seen} parts")
    print(f"  last updated:  {last_updated} parts (includes new parts)")

    sys.exit(0 if fresh else 1)


if __name__ == "__main__":
    main()
