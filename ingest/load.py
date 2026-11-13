"""Week 2 load: turn the saved Mouser JSON into rows in the database.

Run it from the project folder:

    python ingest/load.py

It reads data/raw/mouser/*.json, keeps the newest copy of each part, and inserts parents before
children in one transaction, so a failure leaves the database unchanged. Running it again adds no
duplicates. It reads DATABASE_URL only from the environment (.env locally) and never prints it.
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from sources.mouser import _text, _to_int  # the same "None" and number rules as the adapter

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "mouser"

# Spec rules approved in Milestone 2, Step 5. A null means the description does not state the
# value clearly. It never means "no". The original text stays in parts.raw.
AMP_CATEGORIES = {"Power Outlet Strips"}
MAX_RATED_AMPS = 63  # removes a 200 A DC fuse panel
AMPS_RE = re.compile(r"(?<![\d.])(\d{1,3})\s*-?\s*(?:amps?|amperes?|a)\b", re.I)

RACK_CATEGORIES = {"Racks & Rack Cabinets", "Racks & Rack Cabinet Accessories"}
WIDTH_RE = re.compile(r"(?<![\d.])(19|23)\s*-?\s*(?:\"{1,2}|''|in\b|inch(?:es)?\b)", re.I)
DEPTH_AFTER_RE = re.compile(r"\s*-?\s*(?:deep|depth)\b", re.I)
DEPTH_BEFORE_RE = re.compile(r"depth\s*$", re.I)

INSERT_MANUFACTURER = """
    insert into manufacturers (name) values (%s)
    on conflict (name) do nothing
"""
INSERT_KEYWORD = """
    insert into search_keywords (keyword) values (%s)
    on conflict (keyword) do nothing
"""
INSERT_PART = """
    insert into parts (
        mouser_part_number, manufacturer_id, manufacturer_part_number, description, category,
        availability_text, in_stock_qty, lead_time_days, lifecycle_status, min_order_qty,
        order_multiple, tariff_pct, country_of_origin, rated_amps, rack_width_in,
        product_url, data_as_of, raw
    ) values (
        %(mouser_part_number)s, %(manufacturer_id)s, %(manufacturer_part_number)s, %(description)s,
        %(category)s, %(availability_text)s, %(in_stock_qty)s, %(lead_time_days)s,
        %(lifecycle_status)s, %(min_order_qty)s, %(order_multiple)s, %(tariff_pct)s,
        %(country_of_origin)s, %(rated_amps)s, %(rack_width_in)s, %(product_url)s,
        %(data_as_of)s, %(raw)s
    )
    on conflict (mouser_part_number) do nothing
"""
INSERT_PRICE_BREAK = """
    insert into price_breaks (part_id, quantity, unit_price, currency) values (%s, %s, %s, %s)
    on conflict (part_id, quantity) do nothing
"""
INSERT_ATTRIBUTE = """
    insert into part_attributes (part_id, attribute_name, attribute_value) values (%s, %s, %s)
    on conflict (part_id, attribute_name, attribute_value) do nothing
"""
INSERT_ON_ORDER = """
    insert into part_on_order (part_id, expected_date, quantity) values (%s, %s, %s)
    on conflict (part_id, expected_date) do nothing
"""
INSERT_HIT = """
    insert into part_search_hits (keyword_id, part_id, run_started_at, fetched_at)
    values (%s, %s, %s, %s)
    on conflict (keyword_id, part_id, run_started_at) do nothing
"""

# Row counts before and after each insert give the real number of new rows.
# cursor.rowcount is not a reliable total after executemany.
COUNT_SQL = {
    "manufacturers": "select count(*) from manufacturers",
    "search_keywords": "select count(*) from search_keywords",
    "parts": "select count(*) from parts",
    "price_breaks": "select count(*) from price_breaks",
    "part_attributes": "select count(*) from part_attributes",
    "part_on_order": "select count(*) from part_on_order",
    "part_search_hits": "select count(*) from part_search_hits",
}


def read_raw():
    """Return the newest copy of each part, every keyword, and one hit per keyword + part + run."""
    newest, hits, keywords = {}, {}, set()
    for path in sorted(RAW_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        parts = ((doc.get("response") or {}).get("SearchResults") or {}).get("Parts")
        if doc.get("http_status") != 200 or not isinstance(parts, list):
            continue
        stamp = path.stem.split("_")[0]
        run_started_at = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        fetched_at = datetime.fromisoformat(doc["fetched_at"])
        keyword = doc["keyword"]
        keywords.add(keyword)
        for raw in parts:
            number = raw["MouserPartNumber"]
            if number not in newest or fetched_at >= newest[number][1]:
                newest[number] = (raw, fetched_at)
            key = (keyword, number, run_started_at)
            hits[key] = min(fetched_at, hits.get(key, fetched_at))
    return newest, keywords, hits


def parse_price(text):
    """'$1,234.56' -> Decimal('1234.56'). Decimal keeps the exact price; a float would not."""
    return Decimal(re.sub(r"[^\d.]", "", str(text)))


def parse_lead_time(text):
    """'17 Days' -> 17. Anything else stops the load rather than storing a guess."""
    match = re.fullmatch(r"(\d+)\s+Days?", str(text).strip())
    if not match:
        raise ValueError(f"unreadable lead time: {text!r}")
    return int(match.group(1))


def parse_tariff(raw):
    for message in raw.get("SurchargeMessages") or []:
        if message.get("code") == "TARIFF_US":
            match = re.search(r"(\d+(?:\.\d+)?)%", message.get("message") or "")
            if match:
                return Decimal(match.group(1))
    return None


def parse_country(raw):
    for item in raw.get("TradeCompliance") or []:
        if item.get("ComplianceName") == "Country of Origin":
            value = _text(item.get("ComplianceValue"))
            return None if value == "Not available" else value
    return None


def parse_rated_amps(category, description):
    """One stated amp value on a power strip. Two different values (dual rated) stay null."""
    if category not in AMP_CATEGORIES:
        return None
    values = {int(v) for v in AMPS_RE.findall(description) if 0 < int(v) <= MAX_RATED_AMPS}
    return values.pop() if len(values) == 1 else None


def parse_rack_width(category, description):
    """19 or 23 on a rack product, ignoring numbers that are described as a depth."""
    if category not in RACK_CATEGORIES:
        return None
    values = set()
    for match in WIDTH_RE.finditer(description):
        if DEPTH_BEFORE_RE.search(description[:match.start()]):
            continue
        if DEPTH_AFTER_RE.match(description, match.end()):
            continue
        values.add(int(match.group(1)))
    return values.pop() if len(values) == 1 else None


def part_row(raw, fetched_at, manufacturer_id):
    description, category = raw["Description"], raw["Category"]
    return {
        "mouser_part_number": raw["MouserPartNumber"],
        "manufacturer_id": manufacturer_id,
        "manufacturer_part_number": raw["ManufacturerPartNumber"],
        "description": description,
        "category": category,
        "availability_text": _text(raw.get("Availability")),
        # A missing stock figure is stored as 0, following docs/data_quality.md.
        "in_stock_qty": _to_int(raw.get("AvailabilityInStock")) or 0,
        "lead_time_days": parse_lead_time(raw.get("LeadTime")),
        "lifecycle_status": _text(raw.get("LifecycleStatus")) or "Unknown",
        "min_order_qty": _to_int(raw.get("Min")),
        "order_multiple": _to_int(raw.get("Mult")),
        "tariff_pct": parse_tariff(raw),
        "country_of_origin": parse_country(raw),
        "rated_amps": parse_rated_amps(category, description),
        "rack_width_in": parse_rack_width(category, description),
        "product_url": raw["ProductDetailUrl"],
        "data_as_of": fetched_at,
        "raw": Jsonb(raw),
    }


def insert(cur, label, sql, rows, summary):
    """Insert rows and record how many were new and how many already existed."""
    cur.execute(COUNT_SQL[label])
    before = cur.fetchone()[0]
    if rows:
        cur.executemany(sql, rows)
    cur.execute(COUNT_SQL[label])
    inserted = cur.fetchone()[0] - before
    summary.append((label, len(rows), inserted, len(rows) - inserted))


def load(conn, newest, keywords, hits):
    summary = []
    with conn.cursor() as cur:
        # Parents first.
        names = sorted({raw["Manufacturer"] for raw, _ in newest.values()})
        insert(cur, "manufacturers", INSERT_MANUFACTURER, [(n,) for n in names], summary)
        insert(cur, "search_keywords", INSERT_KEYWORD, [(k,) for k in sorted(keywords)], summary)

        cur.execute("select name, manufacturer_id from manufacturers")
        manufacturer_ids = dict(cur.fetchall())
        cur.execute("select keyword, keyword_id from search_keywords")
        keyword_ids = dict(cur.fetchall())

        rows = [part_row(raw, fetched_at, manufacturer_ids[raw["Manufacturer"]])
                for raw, fetched_at in newest.values()]
        insert(cur, "parts", INSERT_PART, rows, summary)

        cur.execute("select mouser_part_number, part_id from parts")
        part_ids = dict(cur.fetchall())

        # Then children, from the newest copy of each part only.
        breaks, attributes, on_order = [], [], []
        for number, (raw, _) in newest.items():
            part_id = part_ids[number]
            for b in raw.get("PriceBreaks") or []:
                breaks.append((part_id, _to_int(b.get("Quantity")), parse_price(b.get("Price")),
                               b.get("Currency")))
            for a in raw.get("ProductAttributes") or []:
                attributes.append((part_id, a.get("AttributeName"), a.get("AttributeValue")))
            for o in raw.get("AvailabilityOnOrder") or []:
                on_order.append((part_id, datetime.fromisoformat(o["Date"]).date(), o["Quantity"]))
        insert(cur, "price_breaks", INSERT_PRICE_BREAK, breaks, summary)
        insert(cur, "part_attributes", INSERT_ATTRIBUTE, attributes, summary)
        insert(cur, "part_on_order", INSERT_ON_ORDER, on_order, summary)

        hit_rows = [(keyword_ids[keyword], part_ids[number], run_started_at, fetched_at)
                    for (keyword, number, run_started_at), fetched_at in sorted(hits.items())]
        insert(cur, "part_search_hits", INSERT_HIT, hit_rows, summary)
    return summary, rows


def main():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[FAIL] DATABASE_URL is not set.")
        sys.exit(1)

    newest, keywords, hits = read_raw()
    try:
        # One transaction: it commits only if every insert succeeds.
        with psycopg.connect(url, connect_timeout=10) as conn:
            summary, rows = load(conn, newest, keywords, hits)
    except psycopg.Error as error:
        print(f"[FAIL] {type(error).__name__}. Nothing was saved.")
        sys.exit(1)

    print(f"{'table':20} {'read':>7} {'inserted':>9} {'skipped':>8}")
    for label, read, inserted, skipped in summary:
        print(f"{label:20} {read:>7} {inserted:>9} {skipped:>8}")
    amps = Counter(r["rated_amps"] for r in rows if r["rated_amps"] is not None)
    width = Counter(r["rack_width_in"] for r in rows if r["rack_width_in"] is not None)
    print("rated_amps parsed:", sorted(amps.items()))
    print("rack_width_in parsed:", sorted(width.items()))


if __name__ == "__main__":
    main()
