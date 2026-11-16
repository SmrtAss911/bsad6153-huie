"""Week 3 access check: prove the read-only role can read but not write.

Run it from the project folder:

    python scripts/test_app_reader.py

It connects with APP_DATABASE_URL only (the app_reader role) and tries one SELECT, one INSERT,
and one DELETE on the parts table. Each statement runs in its own transaction, which is always
rolled back, so nothing can be kept even if a write were allowed. The DELETE matches only a fake
part number that does not exist. It never prints the connection string.
"""

import os
import sys

import psycopg
from dotenv import load_dotenv

FAKE = "APP-READER-TEST"

TESTS = [
    ("SELECT", "select count(*) from parts", None),
    ("INSERT",
     """insert into parts (mouser_part_number, manufacturer_id, manufacturer_part_number,
            description, category, in_stock_qty, lead_time_days, min_order_qty,
            order_multiple, product_url, data_as_of, raw)
        values (%s, 0, %s, 'access test', 'access test', 0, 0, 1, 1, 'none', now(), '{}')""",
     (FAKE, FAKE)),
    ("DELETE", "delete from parts where mouser_part_number = %s", (FAKE,)),
]


def main():
    load_dotenv()
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        print("[FAIL] APP_DATABASE_URL is not set.")
        sys.exit(1)

    try:
        conn = psycopg.connect(url, connect_timeout=10)
    except psycopg.OperationalError as error:
        print(f"[FAIL] Could not connect using APP_DATABASE_URL: {str(error).strip().splitlines()[0]}")
        sys.exit(1)

    with conn:
        user = conn.execute("select current_user").fetchone()[0]
        conn.rollback()
        print(f"Connected as: {user}")
        for label, sql, params in TESTS:
            try:
                cur = conn.execute(sql, params)
                result = cur.fetchone()[0] if label == "SELECT" else f"{cur.rowcount} row(s) affected"
                print(f"  {label:6}  OK      {result}")
            except psycopg.Error as error:
                message = str(error).strip().splitlines()[0]
                print(f"  {label:6}  DENIED  {type(error).__name__}: {message}")
            finally:
                conn.rollback()  # nothing from any test is ever kept


if __name__ == "__main__":
    main()
