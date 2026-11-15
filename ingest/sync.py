"""Week 3 sync: refresh the database from the Mouser API and record the run in sync_runs.

Run it from the project folder:

    python ingest/sync.py                      # manual run
    python ingest/sync.py --trigger schedule   # what GitHub Actions runs
    python ingest/sync.py --dry-run            # fetch and compare, then roll back

Mouser has no "changed since" filter, so every run re-reads the watch list (every part number
already in the parts table, 10 per call) and re-runs the keyword searches to find new parts.
All API calls happen first, with no database transaction open. Then every write happens in one
transaction, and a row goes into sync_runs whatever the outcome. A row in parts changes only
when one of its business values really changed, so a second run right after the first should
insert and update nothing. Only one sync runs at a time: a run that finds another one holding
the Postgres advisory lock records a failed sync_runs row and exits without fetching.

It reads DATABASE_URL and MOUSER_API_KEY only from the environment (.env locally, secrets in
GitHub Actions) and never prints either. Exit code 1 means the run failed; 0 means success or
partial (partial runs print a warning).
"""

import argparse
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import InvalidOperation
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from fetch import KEYWORDS  # the same 12 searches as the Week 1 fetch
from load import parse_lead_time, parse_price, part_row  # the same parsing rules as the loader
from sources.base import (AccessDenied, BadResponse, RateLimited, SourceNotConfigured,
                          TransientError)
from sources.mouser import MAX_PART_NUMBERS, MouserSource, _text, _to_int

ROOT = Path(__file__).resolve().parent.parent

DELAY_SECONDS = 2.5        # 24 calls/minute, under Mouser's 30/minute
MAX_CALLS = 250            # per run, retries included; about 183 needed; Mouser allows 1,000/day
MAX_PAGES = 3              # keyword pages of 50
LIMIT_RETRIES = 4          # backoff about 5, 10, 20, 40 s, each plus up to 1 s of jitter
TRANSIENT_RETRIES = 3      # timeouts, connection errors, 5xx
BACKOFF_BASE = 5
MISSING_FAIL_SHARE = 0.5   # more than half the watch list missing means the run failed
COUNT_CHANGE_SHARE = 0.2   # fetched count 20% away from the last successful run means partial
LOCK_KEY = (6153, 3)       # advisory lock id (course 6153, week 3): one sync at a time

# Fields a part must have before it is loaded.
REQUIRED_TEXT = ["MouserPartNumber", "Manufacturer", "ManufacturerPartNumber", "Description",
                 "Category", "ProductDetailUrl"]
REQUIRED_FIELDS = REQUIRED_TEXT + ["LeadTime", "Min", "Mult", "PriceBreaks"]

# Every field name in data/sample/mouser_sample.json. A name outside this list is reported as a
# warning, because it may mean Mouser changed its format. It does not stop the load.
EXPECTED_FIELDS = {
    "Availability", "DataSheetUrl", "Description", "FactoryStock", "ImagePath", "Category",
    "LeadTime", "LifecycleStatus", "Manufacturer", "ManufacturerPartNumber", "Min", "Mult",
    "MouserPartNumber", "ProductAttributes", "PriceBreaks", "AlternatePackagings",
    "ProductDetailUrl", "Reeling", "ROHSStatus", "SuggestedReplacement", "MultiSimBlue",
    "UnitWeightKg", "AvailabilityInStock", "AvailabilityOnOrder", "InfoMessages",
    "SurchargeMessages", "ProductCompliance", "TradeCompliance",
}

# parts columns compared to decide whether a row really changed. data_as_of and raw are left
# out on purpose: they differ on every fetch even when nothing that matters has changed.
COMPARED = ["manufacturer_id", "manufacturer_part_number", "description", "category",
            "availability_text", "in_stock_qty", "lead_time_days", "lifecycle_status",
            "min_order_qty", "order_multiple", "tariff_pct", "country_of_origin", "rated_amps",
            "rack_width_in", "product_url"]
PART_COLUMNS = ["mouser_part_number"] + COMPARED + ["data_as_of", "raw"]
STAGED_COLUMNS = ["mouser_part_number", "manufacturer"] + COMPARED[1:] + ["data_as_of", "raw"]


def log(message):
    print(message, flush=True)


def now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- validation

def check_part(raw):
    """Return None if the part can be loaded, or a short reason it can't."""
    if not isinstance(raw, dict):
        return "part is not an object"
    for name in REQUIRED_FIELDS:
        if name not in raw:
            return f"missing field {name}"
    for name in REQUIRED_TEXT:
        if not _text(raw.get(name)):
            return f"empty {name}"
    try:
        parse_lead_time(raw["LeadTime"])
    except ValueError:
        return "unreadable LeadTime"
    for name in ("Min", "Mult"):
        if not _to_int(raw.get(name)):
            return f"bad {name}"
    breaks = raw.get("PriceBreaks")
    if not isinstance(breaks, list):
        return "PriceBreaks is not a list"
    for b in breaks:
        if not isinstance(b, dict) or not _to_int(b.get("Quantity")):
            return "bad price break quantity"
        try:
            if parse_price(b.get("Price")) <= 0:
                return "price is not above 0"
        except (InvalidOperation, ValueError, TypeError):
            return "unreadable price"
        if b.get("Currency") != "USD":
            return "price not in USD"
    for o in raw.get("AvailabilityOnOrder") or []:
        try:
            datetime.fromisoformat(o["Date"])
        except (KeyError, TypeError, ValueError):
            return "unreadable on-order date"
        if not _to_int(o.get("Quantity")):
            return "bad on-order quantity"
    return None


# ---------------------------------------------------------------- API calls

class StopRun(Exception):
    """No more calls should be made this run. fatal=True means the run failed."""

    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


class Caller:
    """Makes API calls at a safe pace, with the same retry policy as fetch.py."""

    def __init__(self, max_calls):
        self.max_calls = max_calls
        self.calls = self.retries = self.successful = 0
        self._last = None

    def call(self, fn, *args, what=""):
        """Return a SearchPage, or None if this call was skipped after retries."""
        limit_tries = transient_tries = 0
        while True:
            if self.calls >= self.max_calls:
                raise StopRun(f"reached the {self.max_calls}-call cap")
            if self._last is not None:
                remaining = DELAY_SECONDS - (time.monotonic() - self._last)
                if remaining > 0:
                    time.sleep(remaining)
            self.calls += 1
            self._last = time.monotonic()
            try:
                page = fn(*args)
                self.successful += 1
                return page
            except (RateLimited, AccessDenied) as exc:
                # A 401/403 before anything has worked is almost certainly a bad key.
                if isinstance(exc, AccessDenied) and self.successful == 0:
                    raise StopRun(f"{type(exc).__name__} on the first call: check MOUSER_API_KEY",
                                  fatal=True) from None
                if limit_tries >= LIMIT_RETRIES:
                    raise StopRun(f"still rate limited after {LIMIT_RETRIES} retries") from None
                limit_tries += 1
                self._backoff(limit_tries, exc, what)
            except TransientError as exc:
                if transient_tries >= TRANSIENT_RETRIES:
                    log(f"  ERROR {what}: {exc}; skipped after {TRANSIENT_RETRIES} retries")
                    return None
                transient_tries += 1
                self._backoff(transient_tries, exc, what)
            except BadResponse as exc:
                log(f"  ERROR {what}: {exc}; skipped")
                return None

    def _backoff(self, attempt, exc, what):
        delay = BACKOFF_BASE * 2 ** (attempt - 1) + random.uniform(0, 1)
        self.retries += 1
        log(f"  {exc} on {what}: retry {attempt} in {delay:.1f} s")
        time.sleep(delay)


class Sync:
    def __init__(self, source, max_calls):
        self.source = source
        self.caller = Caller(max_calls)
        self.started_at = now()
        self.parts = {}            # MouserPartNumber -> (raw, fetched_at), newest copy wins
        self.hits = {}             # (keyword, MouserPartNumber) -> earliest fetched_at
        self.keywords = set()
        self.rejected = Counter()  # reason -> count
        self.rejected_numbers = set()
        self.unexpected_fields = set()
        self.skipped_calls = 0
        self.stopped = None        # StopRun, if the fetch stopped early

    def accept(self, raw, fetched_at, keyword=None):
        reason = check_part(raw)
        if reason:
            self.rejected[reason] += 1
            if isinstance(raw, dict) and raw.get("MouserPartNumber"):
                self.rejected_numbers.add(raw["MouserPartNumber"])
            return
        number = raw["MouserPartNumber"]
        self.unexpected_fields.update(set(raw) - EXPECTED_FIELDS)
        self.parts[number] = (raw, fetched_at)
        if keyword:
            key = (keyword, number)
            self.hits[key] = min(fetched_at, self.hits.get(key, fetched_at))

    def fetch_watch_list(self, numbers):
        batches = [numbers[i:i + MAX_PART_NUMBERS] for i in range(0, len(numbers), MAX_PART_NUMBERS)]
        log(f"Watch list: {len(numbers)} part numbers in {len(batches)} calls")
        for index, batch in enumerate(batches, 1):
            page = self.caller.call(self.source.search_part_numbers, batch,
                                    what=f"watch batch {index}")
            if page is None:
                self.skipped_calls += 1
                continue
            fetched_at = now()
            wanted = set(batch)
            # Keep exact matches only, in case Mouser returns near matches too.
            for raw in page.parts:
                if isinstance(raw, dict) and raw.get("MouserPartNumber") in wanted:
                    self.accept(raw, fetched_at)
            if index % 25 == 0 or index == len(batches):
                log(f"  {index}/{len(batches)} batches, {len(self.parts)} parts so far")

    def fetch_keywords(self, keywords, max_pages):
        log(f"Keyword search: {len(keywords)} keywords, up to {max_pages} pages each")
        size = self.source.max_page_size
        for keyword in keywords:
            self.keywords.add(keyword)
            for page_index in range(max_pages):
                offset = page_index * size
                page = self.caller.call(self.source.search, keyword, offset, size,
                                        what=f"'{keyword}' page {page_index + 1}")
                if page is None:
                    self.skipped_calls += 1
                    break
                fetched_at = now()
                for raw in page.parts:
                    self.accept(raw, fetched_at, keyword)
                if (len(page.parts) < size
                        or (page.total is not None and offset + len(page.parts) >= page.total)):
                    break
        log(f"  done, {len(self.parts)} unique valid parts in total")

    def fetch(self, watch_numbers, use_keywords, max_pages):
        try:
            self.fetch_watch_list(watch_numbers)
            if use_keywords:
                self.fetch_keywords(KEYWORDS, max_pages)
        except StopRun as exc:
            self.stopped = exc
            log(f"STOPPED: {exc}")


# ---------------------------------------------------------------- database

STAGING_SQL = """
    create temp table stg_parts (
        mouser_part_number text primary key, manufacturer text not null,
        manufacturer_part_number text, description text, category text,
        availability_text text, in_stock_qty integer, lead_time_days integer,
        lifecycle_status text, min_order_qty integer, order_multiple integer,
        tariff_pct numeric(6,2), country_of_origin text, rated_amps integer,
        rack_width_in integer, product_url text, data_as_of timestamptz, raw jsonb
    ) on commit drop;
    create temp table stg_breaks (
        mouser_part_number text, quantity integer, unit_price numeric(12,4), currency text,
        primary key (mouser_part_number, quantity)) on commit drop;
    create temp table stg_attrs (
        mouser_part_number text, attribute_name text, attribute_value text,
        primary key (mouser_part_number, attribute_name, attribute_value)) on commit drop;
    create temp table stg_orders (
        mouser_part_number text, expected_date date, quantity integer,
        primary key (mouser_part_number, expected_date)) on commit drop;
    create temp table stg_hits (
        keyword text, mouser_part_number text, fetched_at timestamptz,
        primary key (keyword, mouser_part_number)) on commit drop;
"""

UPSERT_MANUFACTURERS = """
    insert into manufacturers (name) select distinct manufacturer from stg_parts
    on conflict (name) do nothing
    returning 1
"""

UPSERT_KEYWORD = "insert into search_keywords (keyword) values (%s) on conflict (keyword) do nothing"

# Insert new parts; update an existing part only when a compared column really differs.
# xmax = 0 on a returned row means it was inserted; otherwise it was updated. Unchanged rows
# are not returned at all.
UPSERT_PARTS = f"""
    insert into parts ({", ".join(PART_COLUMNS)})
    select s.mouser_part_number, m.manufacturer_id, {", ".join("s." + c for c in COMPARED[1:])},
           s.data_as_of, s.raw
    from stg_parts s join manufacturers m on m.name = s.manufacturer
    on conflict (mouser_part_number) do update set
        {", ".join(f"{c} = excluded.{c}" for c in COMPARED)},
        data_as_of = excluded.data_as_of, raw = excluded.raw, last_updated_at = now()
    where ({", ".join("parts." + c for c in COMPARED)})
          is distinct from ({", ".join("excluded." + c for c in COMPARED)})
    returning part_id, (xmax = 0) as inserted
"""

# Children: for every part fetched this run, make the stored rows match what Mouser sent.
UPSERT_BREAKS = """
    insert into price_breaks (part_id, quantity, unit_price, currency)
    select p.part_id, s.quantity, s.unit_price, s.currency
    from stg_breaks s join parts p using (mouser_part_number)
    on conflict (part_id, quantity) do update set
        unit_price = excluded.unit_price, currency = excluded.currency, last_updated_at = now()
    where (price_breaks.unit_price, price_breaks.currency)
          is distinct from (excluded.unit_price, excluded.currency)
    returning part_id, (xmax = 0) as inserted
"""
DELETE_STALE_BREAKS = """
    delete from price_breaks pb using parts p, stg_parts sp
    where pb.part_id = p.part_id and p.mouser_part_number = sp.mouser_part_number
      and not exists (select 1 from stg_breaks s
                      where s.mouser_part_number = p.mouser_part_number
                        and s.quantity = pb.quantity)
    returning pb.part_id
"""
UPSERT_ATTRS = """
    insert into part_attributes (part_id, attribute_name, attribute_value)
    select p.part_id, s.attribute_name, s.attribute_value
    from stg_attrs s join parts p using (mouser_part_number)
    on conflict (part_id, attribute_name, attribute_value) do nothing
    returning part_id, true as inserted
"""
DELETE_STALE_ATTRS = """
    delete from part_attributes pa using parts p, stg_parts sp
    where pa.part_id = p.part_id and p.mouser_part_number = sp.mouser_part_number
      and not exists (select 1 from stg_attrs s
                      where s.mouser_part_number = p.mouser_part_number
                        and s.attribute_name = pa.attribute_name
                        and s.attribute_value = pa.attribute_value)
    returning pa.part_id
"""
UPSERT_ORDERS = """
    insert into part_on_order (part_id, expected_date, quantity)
    select p.part_id, s.expected_date, s.quantity
    from stg_orders s join parts p using (mouser_part_number)
    on conflict (part_id, expected_date) do update set
        quantity = excluded.quantity, last_updated_at = now()
    where part_on_order.quantity is distinct from excluded.quantity
    returning part_id, (xmax = 0) as inserted
"""
DELETE_STALE_ORDERS = """
    delete from part_on_order po using parts p, stg_parts sp
    where po.part_id = p.part_id and p.mouser_part_number = sp.mouser_part_number
      and not exists (select 1 from stg_orders s
                      where s.mouser_part_number = p.mouser_part_number
                        and s.expected_date = po.expected_date)
    returning po.part_id
"""
# A part whose row did not change but whose children did is still an update.
TOUCH_PARTS = """
    update parts set last_updated_at = now(), data_as_of = s.data_as_of
    from stg_parts s
    where parts.mouser_part_number = s.mouser_part_number and parts.part_id = any(%s)
"""
INSERT_HITS = """
    insert into part_search_hits (keyword_id, part_id, run_started_at, fetched_at)
    select k.keyword_id, p.part_id, %s, h.fetched_at
    from stg_hits h
    join search_keywords k using (keyword)
    join parts p using (mouser_part_number)
    on conflict (keyword_id, part_id, run_started_at) do nothing
"""
INSERT_RUN = """
    insert into sync_runs (started_at, finished_at, status, records_fetched, records_inserted,
                           records_updated, error_message, trigger)
    values (%s, %s, %s, %s, %s, %s, %s, %s)
    returning run_id
"""


def copy_rows(cur, table, columns, rows):
    with cur.copy(f"copy {table} ({', '.join(columns)}) from stdin") as copy:
        for row in rows:
            copy.write_row(row)


def stage(cur, sync):
    """Put this run's valid parts and their children into temp tables."""
    parts, breaks, attrs, orders = [], {}, set(), {}
    for number, (raw, fetched_at) in sync.parts.items():
        row = part_row(raw, fetched_at, None)
        row["manufacturer"] = raw["Manufacturer"]
        parts.append([row[c] for c in STAGED_COLUMNS])
        for b in raw.get("PriceBreaks") or []:
            breaks[(number, _to_int(b["Quantity"]))] = (parse_price(b["Price"]), b["Currency"])
        for a in raw.get("ProductAttributes") or []:
            name, value = _text(a.get("AttributeName")), _text(a.get("AttributeValue"))
            if name and value:
                attrs.add((number, name, value))
        for o in raw.get("AvailabilityOnOrder") or []:
            day = datetime.fromisoformat(o["Date"]).date()
            orders.setdefault((number, day), _to_int(o["Quantity"]))  # first one wins, as in load.py
    copy_rows(cur, "stg_parts", STAGED_COLUMNS, parts)
    copy_rows(cur, "stg_breaks", ["mouser_part_number", "quantity", "unit_price", "currency"],
              [(n, q, p, c) for (n, q), (p, c) in breaks.items()])
    copy_rows(cur, "stg_attrs", ["mouser_part_number", "attribute_name", "attribute_value"], attrs)
    copy_rows(cur, "stg_orders", ["mouser_part_number", "expected_date", "quantity"],
              [(n, d, q) for (n, d), q in orders.items()])
    copy_rows(cur, "stg_hits", ["keyword", "mouser_part_number", "fetched_at"],
              [(k, n, t) for (k, n), t in sync.hits.items()])


def write(conn, sync):
    """All writes for one run, inside the caller's transaction. Returns the counts."""
    counts = Counter()
    with conn.cursor() as cur:
        cur.execute(STAGING_SQL)
        stage(cur, sync)

        # Parents first.
        cur.execute(UPSERT_MANUFACTURERS)
        counts["manufacturers inserted"] = len(cur.fetchall())
        for keyword in sorted(sync.keywords):
            cur.execute(UPSERT_KEYWORD, (keyword,))

        cur.execute(UPSERT_PARTS)
        changed_parts = {}
        for part_id, inserted in cur.fetchall():
            changed_parts[part_id] = inserted
        inserted_ids = {p for p, ins in changed_parts.items() if ins}
        counts["parts inserted"] = len(inserted_ids)
        counts["parts updated (row)"] = len(changed_parts) - len(inserted_ids)

        # Then children.
        child_changed = set()
        for label, upsert, delete in [("price_breaks", UPSERT_BREAKS, DELETE_STALE_BREAKS),
                                      ("part_attributes", UPSERT_ATTRS, DELETE_STALE_ATTRS),
                                      ("part_on_order", UPSERT_ORDERS, DELETE_STALE_ORDERS)]:
            cur.execute(upsert)
            for part_id, inserted in cur.fetchall():
                counts[f"{label} {'inserted' if inserted else 'updated'}"] += 1
                child_changed.add(part_id)
            cur.execute(delete)
            deleted = cur.fetchall()
            counts[f"{label} deleted"] = len(deleted)
            child_changed.update(part_id for (part_id,) in deleted)

        touch = sorted(child_changed - set(changed_parts))
        if touch:
            cur.execute(TOUCH_PARTS, (touch,))
        counts["parts updated (children only)"] = len(touch)

        cur.execute(INSERT_HITS, (sync.started_at,))
        counts["part_search_hits inserted"] = max(cur.rowcount, 0)

    counts["records_inserted"] = counts["parts inserted"]
    counts["records_updated"] = counts["parts updated (row)"] + len(touch)
    return counts


def read_start_state(url):
    """The watch list, and records_fetched from the last successful run (None if none)."""
    with psycopg.connect(url, connect_timeout=10) as conn:
        numbers = [r[0] for r in conn.execute(
            "select mouser_part_number from parts order by part_id").fetchall()]
        last = conn.execute(
            "select records_fetched from sync_runs where status = 'success' "
            "order by finished_at desc limit 1").fetchone()
    return numbers, (last[0] if last else None)


def record_run(url, sync, status, fetched, counts, reasons, trigger):
    message = "; ".join(reasons)[:500] or None
    with psycopg.connect(url, connect_timeout=10) as conn:
        run_id = conn.execute(INSERT_RUN, (
            sync.started_at, now(), status, fetched, counts.get("records_inserted", 0),
            counts.get("records_updated", 0), message, trigger)).fetchone()[0]
    return run_id


# ---------------------------------------------------------------- run

def judge(sync, watch_numbers, previous_fetched):
    """Decide the status from the fetch alone. Returns (status, reasons)."""
    failed, partial = [], []
    fetched = len(sync.parts)
    if sync.stopped and sync.stopped.fatal:
        failed.append(f"stopped: {sync.stopped}")
    elif sync.stopped:
        partial.append(f"stopped early: {sync.stopped}")
    if fetched == 0:
        failed.append("0 valid parts fetched")
    missing = set(watch_numbers) - set(sync.parts) - sync.rejected_numbers
    if watch_numbers and len(missing) / len(watch_numbers) > MISSING_FAIL_SHARE:
        failed.append(f"{len(missing)} of {len(watch_numbers)} watched parts missing")
    if sync.skipped_calls:
        partial.append(f"{sync.skipped_calls} calls skipped after errors")
    if sync.rejected:
        partial.append(f"{sum(sync.rejected.values())} parts rejected by validation")
    if previous_fetched and fetched and abs(fetched - previous_fetched) / previous_fetched > COUNT_CHANGE_SHARE:
        partial.append(f"fetched {fetched} parts vs {previous_fetched} last successful run")
    if failed:
        return "failed", failed + partial, missing
    return ("partial" if partial else "success"), partial, missing


def summary(sync, status, missing, counts, elapsed):
    log("")
    log("Summary")
    log(f"  status:          {status}")
    log(f"  calls made:      {sync.caller.calls} (cap {sync.caller.max_calls}, retries included)")
    log(f"  retries:         {sync.caller.retries}")
    log(f"  skipped calls:   {sync.skipped_calls}")
    log(f"  parts fetched:   {len(sync.parts)} unique valid")
    log(f"  rejected:        {sum(sync.rejected.values())}")
    for reason, n in sync.rejected.most_common():
        log(f"    {reason:30} {n}")
    log(f"  watched missing: {len(missing)}")
    if sync.unexpected_fields:
        log(f"  WARNING new field names from Mouser: {', '.join(sorted(sync.unexpected_fields))}")
    for label in sorted(k for k in counts if k not in ("records_inserted", "records_updated")):
        log(f"  {label:32} {counts[label]}")
    log(f"  records_inserted: {counts.get('records_inserted', 0)}")
    log(f"  records_updated:  {counts.get('records_updated', 0)}")
    log(f"  elapsed:         {elapsed:.0f} s")


def main():
    parser = argparse.ArgumentParser(description="Sync Mouser part data into the database.")
    parser.add_argument("--trigger", choices=["schedule", "manual"], default="manual")
    parser.add_argument("--no-keywords", action="store_true",
                        help="only refresh known parts; skip the keyword searches")
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and compare, then roll back; writes nothing, not even sync_runs")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")  # does not override variables already set (GitHub secrets)
    url = os.environ.get("DATABASE_URL")
    if not url:
        log("[FAIL] DATABASE_URL is not set.")
        sys.exit(1)
    try:
        source = MouserSource.from_env()
    except SourceNotConfigured as exc:
        log(f"[FAIL] Not configured: {exc}")
        sys.exit(1)

    sync = Sync(source, args.max_calls)

    # One sync at a time. The lock lives as long as lock_conn, so Postgres releases it by
    # itself if this script crashes or is stopped; it can never be left stuck.
    try:
        lock_conn = psycopg.connect(url, connect_timeout=10, autocommit=True)
        got_lock = lock_conn.execute("select pg_try_advisory_lock(%s, %s)", LOCK_KEY).fetchone()[0]
    except psycopg.Error as exc:
        log(f"[FAIL] could not connect to take the sync lock ({type(exc).__name__}). No run recorded.")
        sys.exit(1)
    if not got_lock:
        lock_conn.close()
        reasons = ["another sync is running; this run did nothing"]
        log(f"[FAIL] {reasons[0]}")
        if not args.dry_run:
            try:
                run_id = record_run(url, sync, "failed", 0, Counter(), reasons, args.trigger)
                log(f"  sync_runs row:   run_id {run_id}")
            except psycopg.Error as exc:
                log(f"[FAIL] could not write sync_runs ({type(exc).__name__}).")
        sys.exit(1)

    try:
        run(args, url, sync, lock_conn)
    finally:
        try:
            lock_conn.execute("select pg_advisory_unlock(%s, %s)", LOCK_KEY)
        except psycopg.Error:
            pass  # the connection is gone, and the lock went with it
        lock_conn.close()


def lock_held(lock_conn):
    """True if the connection holding the sync lock is still alive."""
    try:
        lock_conn.execute("select 1")
        return True
    except psycopg.Error:
        return False


def run(args, url, sync, lock_conn):
    try:
        watch_numbers, previous_fetched = read_start_state(url)
    except psycopg.Error as exc:
        log(f"[FAIL] could not read the watch list ({type(exc).__name__}). No run recorded.")
        sys.exit(1)

    started = time.monotonic()
    log(f"Sync started {sync.started_at:%Y-%m-%d %H:%M:%S} UTC, trigger={args.trigger}"
        f"{', DRY RUN' if args.dry_run else ''}")
    sync.fetch(watch_numbers, not args.no_keywords, args.max_pages)

    status, reasons, missing = judge(sync, watch_numbers, previous_fetched)
    counts = Counter()
    if status != "failed" and not lock_held(lock_conn):
        # Without the lock another sync could be writing too, so write nothing.
        status = "failed"
        reasons.insert(0, "lost the sync lock during the fetch; nothing written")
    if status != "failed":
        try:
            with psycopg.connect(url, connect_timeout=10) as conn:
                counts = write(conn, sync)
                if args.dry_run:
                    conn.rollback()
                    log("DRY RUN: every change was rolled back.")
                # Otherwise leaving the with block commits the one transaction.
        except psycopg.Error as exc:
            # Class and SQLSTATE only: the message text could include row values.
            status = "failed"
            reasons.insert(0, f"database error ({type(exc).__name__}, {exc.sqlstate}); rolled back")
            counts = Counter()
    summary(sync, status, missing, counts, time.monotonic() - started)

    if not args.dry_run:
        try:
            run_id = record_run(url, sync, status, len(sync.parts), counts, reasons, args.trigger)
            log(f"  sync_runs row:   run_id {run_id}")
        except psycopg.Error as exc:
            log(f"[FAIL] could not write sync_runs ({type(exc).__name__}).")
            sys.exit(1)

    for reason in reasons:
        log(f"  reason: {reason}")
    if status == "partial" and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::sync partial: {'; '.join(reasons)[:500]}", flush=True)
    sys.exit(1 if status == "failed" else 0)


if __name__ == "__main__":
    main()
