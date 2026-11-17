"""Run db/quality_checks.sql as app_reader, read-only, and print each Qn result."""
import os, re, sys
import psycopg
from dotenv import load_dotenv

load_dotenv()  # loads .env from the current folder; nothing from it is printed
url = os.environ.get("APP_DATABASE_URL")
if not url:
    sys.exit("[FAIL] APP_DATABASE_URL is not set.")

sql = open(sys.argv[1], encoding="utf-8").read()
parts = re.split(r"(?m)^-- (Q\d+):", sql)[1:]   # ["Q1", " title\nSQL...", "Q2", ...]

try:
    with psycopg.connect(url, connect_timeout=10) as conn:
        conn.read_only = True   # every transaction is READ ONLY, on top of app_reader's grants
        now, user = conn.execute("select now(), current_user").fetchone()
        print(f"checked_at {now:%Y-%m-%d %H:%M:%S} UTC as {user}")
        for qid, body in zip(parts[0::2], parts[1::2]):
            title, _, stmt = body.partition("\n")
            cur = conn.execute(stmt)
            print(f"\n== {qid}:{title}")
            print(" | ".join(d.name for d in cur.description))
            for row in cur.fetchall():
                print(" | ".join(str(v) for v in row))
except psycopg.Error as error:
    print(f"[FAIL] {type(error).__name__}: {str(error).strip().splitlines()[0]}")
    sys.exit(1)
