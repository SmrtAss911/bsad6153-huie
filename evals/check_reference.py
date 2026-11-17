"""Run each golden question's reference SQL and save the answers (Milestone 3).

Run it from the project folder:

    python evals/check_reference.py                    # run all, save evals/results/<UTC time>.json
    python evals/check_reference.py --diff A.json B.json   # compare two saved result files

It connects with APP_DATABASE_URL only (the read-only app_reader role), never DATABASE_URL, in a
read-only session, and never prints the connection string. Questions with no reference_sql are
expected to be declined, so they are skipped.

Exit code 0 means every query ran and every answer was non-empty; 1 means a query failed or
returned nothing, or the files could not be read.
"""

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evals" / "golden_questions.csv"
RESULTS = ROOT / "evals" / "results"
MAX_ROWS = 200           # rows kept per question in the result file
STATEMENT_TIMEOUT = "30s"


def to_text(value):
    """Make a database value safe for JSON: numbers and dates become text, None stays None."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (Decimal, timedelta)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def short_error(error):
    return f"{type(error).__name__}: {str(error).strip().splitlines()[0]}"


def load_questions():
    with QUESTIONS.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_all():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        print("[FAIL] APP_DATABASE_URL is not set. This script never uses DATABASE_URL.")
        return 1

    questions = load_questions()
    results = []
    try:
        with psycopg.connect(url, connect_timeout=30) as conn:
            conn.read_only = True
            conn.execute(f"set statement_timeout = '{STATEMENT_TIMEOUT}'")
            conn.commit()
            user, checked_at = conn.execute("select current_user, now()").fetchone()
            for q in questions:
                entry = {"id": q["id"], "category": q["category"],
                         "expected": q["correct_behavior"].split(":")[0]}
                sql = q["reference_sql"].strip()
                if not sql:
                    entry.update(status="skipped", note="no reference SQL; should be declined")
                    results.append(entry)
                    continue
                try:
                    cur = conn.execute(sql)
                    rows = cur.fetchall()
                    entry.update(status="ok", row_count=len(rows), non_empty=bool(rows),
                                 columns=[d.name for d in cur.description],
                                 rows=[[to_text(v) for v in r] for r in rows[:MAX_ROWS]],
                                 truncated=len(rows) > MAX_ROWS)
                except psycopg.Error as error:
                    entry.update(status="error", error=short_error(error))
                conn.rollback()
                results.append(entry)
    except psycopg.Error as error:
        print(f"[FAIL] could not connect: {short_error(error)}")
        return 1

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{stamp}.json"
    out.write_text(json.dumps({"checked_at": checked_at.isoformat(), "db_user": user,
                               "questions_file": str(QUESTIONS.relative_to(ROOT)),
                               "results": results}, indent=2), encoding="utf-8")

    print(f"Reference check as {user}, {checked_at:%Y-%m-%d %H:%M} UTC")
    print(f"{'id':6} {'expected':19} {'status':8} {'rows':>5}  non-empty")
    bad = 0
    for r in results:
        if r["status"] == "ok":
            flag = "yes" if r["non_empty"] else "NO"
            bad += not r["non_empty"]
            print(f"{r['id']:6} {r['expected']:19} {'ok':8} {r['row_count']:>5}  {flag}")
        elif r["status"] == "error":
            bad += 1
            print(f"{r['id']:6} {r['expected']:19} {'ERROR':8} {'':>5}  {r['error']}")
        else:
            print(f"{r['id']:6} {r['expected']:19} {'skipped':8} {'':>5}  (decline by design)")
    ran = sum(r["status"] != "skipped" for r in results)
    print(f"\n{ran} queries run, {ran - bad} ok and non-empty, {bad} problem(s), "
          f"{len(results) - ran} skipped")
    print(f"Saved {out.relative_to(ROOT)}")
    return 1 if bad else 0


def diff(path_a, path_b):
    try:
        a = json.loads(Path(path_a).read_text(encoding="utf-8"))
        b = json.loads(Path(path_b).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"[FAIL] could not read a result file: {error}")
        return 1
    print(f"A: {path_a} ({a['checked_at']})")
    print(f"B: {path_b} ({b['checked_at']})\n")
    by_id_a = {r["id"]: r for r in a["results"]}
    by_id_b = {r["id"]: r for r in b["results"]}
    changed = 0
    for qid in sorted(set(by_id_a) | set(by_id_b)):
        ra, rb = by_id_a.get(qid), by_id_b.get(qid)
        if ra is None or rb is None:
            print(f"{qid}: only in {'B' if ra is None else 'A'}")
            changed += 1
            continue
        notes = []
        if ra["status"] != rb["status"]:
            notes.append(f"status {ra['status']} -> {rb['status']}")
        if ra["status"] == rb["status"] == "ok":
            if ra["row_count"] != rb["row_count"]:
                notes.append(f"rows {ra['row_count']} -> {rb['row_count']}")
            if ra["columns"] != rb["columns"]:
                notes.append("columns changed")
            else:
                rows_a = {json.dumps(r) for r in ra["rows"]}
                rows_b = {json.dumps(r) for r in rb["rows"]}
                only_a, only_b = len(rows_a - rows_b), len(rows_b - rows_a)
                if only_a or only_b:
                    notes.append(f"{only_a} row(s) only in A, {only_b} only in B")
        if notes:
            changed += 1
            print(f"{qid}: " + "; ".join(notes))
        else:
            print(f"{qid}: same")
    print(f"\n{changed} of {len(set(by_id_a) | set(by_id_b))} questions changed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--diff", nargs=2, metavar=("A", "B"),
                        help="compare two saved result files instead of running the queries")
    args = parser.parse_args()
    sys.exit(diff(*args.diff) if args.diff else run_all())


if __name__ == "__main__":
    main()
