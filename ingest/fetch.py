"""Week 1 fetch: call a part-data API and save every raw response to data/raw/<source>/.

Run it from the project folder:

    python ingest/fetch.py --source mouser

It reads keys only from .env, waits between calls to stay under the API's limits, backs off
and retries when the API says to slow down, and ends with a summary. It never prints a key.
"""

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from sources.base import (AccessDenied, BadResponse, RateLimited, SourceNotConfigured,
                          TransientError)
from sources.digikey import DigiKeySource
from sources.mouser import MouserSource

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {"mouser": MouserSource, "digikey": DigiKeySource}

# Searches that match my decision: standard datacenter parts on a weekly pick list.
KEYWORDS = [
    "cat6 patch cable", "cat6a snagless", "fiber patch cord lc", "c13 c14 power cord",
    "rack pdu", "zero u pdu", "server rack shelf", "cable manager 1u",
    "keystone jack cat6", "rack cage nut", "sfp transceiver", "rack mount power strip",
]

DELAY_SECONDS = 2.5      # 24 calls/minute, under Mouser's 30/minute
MAX_PAGES = 3            # per keyword
MAX_CALLS = 100          # per run, retries included; Mouser allows 1,000/day
LIMIT_RETRIES = 4        # backoff about 5, 10, 20, 40 s, each plus up to 1 s of jitter
TRANSIENT_RETRIES = 3    # timeouts, connection errors, 5xx
BACKOFF_BASE = 5

# Normalized fields whose gaps are counted and reported in the summary.
MISSING_FIELDS = ["manufacturer_part_number", "availability_text", "in_stock_qty", "lead_time",
                  "lifecycle_status", "price_breaks", "attributes"]


def log(message):
    print(message, flush=True)


class StopRun(Exception):
    """Something that means no more calls should be made this run."""


class Fetcher:
    def __init__(self, source, max_calls):
        self.source = source
        self.max_calls = max_calls
        self.run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.raw_dir = ROOT / "data" / "raw" / source.name
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.stats = dict.fromkeys(["calls", "retries", "errors", "skipped_pages", "pages_saved",
                                    "parts", "malformed_parts", "price_breaks", "attributes"], 0)
        self.successful_calls = 0
        self.unique_parts = set()
        self.manufacturers = set()
        self.error_log = []
        self.missing = Counter()
        self.stopped = None
        self._last_call = None

    def _wait(self):
        """Keep at least DELAY_SECONDS between the start of one call and the next."""
        if self._last_call is not None:
            remaining = DELAY_SECONDS - (time.monotonic() - self._last_call)
            if remaining > 0:
                time.sleep(remaining)

    def _call(self, keyword, offset):
        if self.stats["calls"] >= self.max_calls:
            raise StopRun(f"reached the {self.max_calls}-call cap for this run")
        self._wait()
        self.stats["calls"] += 1
        self._last_call = time.monotonic()
        return self.source.search(keyword, offset, self.source.max_page_size)

    def _backoff(self, attempt, exc, keyword, offset):
        delay = BACKOFF_BASE * 2 ** (attempt - 1) + random.uniform(0, 1)
        self.stats["retries"] += 1
        log(f"  {exc} on '{keyword}' at record {offset}: retry {attempt} in {delay:.1f} s")
        time.sleep(delay)

    def _error(self, keyword, offset, message):
        self.stats["errors"] += 1
        self.error_log.append(f"'{keyword}' at record {offset}: {message}")
        log(f"  ERROR '{keyword}' at record {offset}: {message}")

    def fetch_page(self, keyword, offset):
        """One page, with the retry policy. Returns a SearchPage, or None if the page is skipped."""
        limit_tries = transient_tries = 0
        while True:
            try:
                page = self._call(keyword, offset)
                self.successful_calls += 1
                return page
            except (RateLimited, AccessDenied) as exc:
                # A 403 before anything has worked is almost certainly a bad key, not a limit.
                if isinstance(exc, AccessDenied) and self.successful_calls == 0:
                    raise StopRun(f"{exc} on the first call: check the API key in .env") from None
                if limit_tries >= LIMIT_RETRIES:
                    raise StopRun(f"still limited after {LIMIT_RETRIES} retries ({exc})") from None
                limit_tries += 1
                self._backoff(limit_tries, exc, keyword, offset)
            except TransientError as exc:
                if transient_tries >= TRANSIENT_RETRIES:
                    self._error(keyword, offset, f"{exc}; skipped after {TRANSIENT_RETRIES} retries")
                    self.stats["skipped_pages"] += 1
                    return None
                transient_tries += 1
                self._backoff(transient_tries, exc, keyword, offset)
            except BadResponse as exc:
                # Retrying the same request would get the same answer, so save it and move on.
                self._error(keyword, offset, str(exc))
                self._save(keyword, offset, exc.http_status, exc.body, suffix="_error")
                self.stats["skipped_pages"] += 1
                return None

    def _save(self, keyword, offset, http_status, response, suffix=""):
        slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
        page_number = offset // self.source.max_page_size + 1
        path = self.raw_dir / f"{self.run_stamp}_{slug}_p{page_number}{suffix}.json"
        record = {
            "source": self.source.name,
            "keyword": keyword,
            "startingRecord": offset,
            "records": self.source.max_page_size,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "http_status": http_status,
            "response": response,  # exactly what the API sent (the key is never in here)
        }
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    def _count(self, parts):
        for raw_part in parts:
            if not isinstance(raw_part, dict):
                self.stats["malformed_parts"] += 1
                continue
            try:
                part = self.source.normalize(raw_part)
            except BadResponse:
                self.stats["malformed_parts"] += 1
                continue
            self.stats["parts"] += 1
            self.unique_parts.add(part.source_part_number)
            if part.manufacturer:
                self.manufacturers.add(part.manufacturer)
            self.stats["price_breaks"] += len(part.price_breaks)
            self.stats["attributes"] += len(part.attributes)
            for name in MISSING_FIELDS:
                if getattr(part, name) in (None, "", []):
                    self.missing[name] += 1

    def run(self, keywords, max_pages):
        try:
            for keyword in keywords:
                for page_index in range(max_pages):
                    offset = page_index * self.source.max_page_size
                    page = self.fetch_page(keyword, offset)
                    if page is None:
                        break  # this keyword's page was skipped; move to the next keyword
                    self._save(keyword, offset, page.http_status, page.raw)
                    self.stats["pages_saved"] += 1
                    self._count(page.parts)
                    log(f"  '{keyword}' page {page_index + 1}: {len(page.parts)} parts "
                        f"(API says {page.total} exist)")
                    # Stop paging this keyword once there is nothing more to get.
                    if (len(page.parts) < self.source.max_page_size
                            or (page.total is not None and offset + len(page.parts) >= page.total)):
                        break
        except StopRun as exc:
            self.stopped = str(exc)
            log(f"STOPPED: {exc}")

    def summary(self, elapsed):
        s = self.stats
        log("")
        log("Summary")
        log(f"  source:          {self.source.name}")
        log(f"  calls made:      {s['calls']} (cap {self.max_calls}, retries included)")
        log(f"  retries:         {s['retries']}")
        log(f"  errors:          {s['errors']}")
        log(f"  skipped pages:   {s['skipped_pages']}")
        log(f"  raw files saved: {s['pages_saved']} in {self.raw_dir.relative_to(ROOT)}")
        log(f"  part records:    {s['parts']} ({len(self.unique_parts)} unique part numbers)")
        log(f"  price breaks:    {s['price_breaks']}")
        log(f"  attributes:      {s['attributes']}")
        log(f"  manufacturers:   {len(self.manufacturers)}")
        log(f"  malformed parts: {s['malformed_parts']}")
        log(f"  missing fields (of {s['parts']} part records):")
        for name in MISSING_FIELDS:
            log(f"    {name:25} {self.missing[name]}")
        log(f"  elapsed:         {elapsed:.0f} s")
        for line in self.error_log:
            log(f"  error: {line}")
        if self.stopped:
            log(f"  stopped early:   {self.stopped}")


def main():
    parser = argparse.ArgumentParser(description="Fetch raw part data into data/raw/<source>/.")
    parser.add_argument("--source", choices=sorted(SOURCES), default="mouser")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="pages per keyword")
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS, help="API calls per run")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    try:
        source = SOURCES[args.source].from_env()
    except SourceNotConfigured as exc:
        log(f"Not configured: {exc}")
        sys.exit(2)

    log(f"Fetching from {source.name}: {len(KEYWORDS)} keywords, up to {args.max_pages} "
        f"pages each, {DELAY_SECONDS} s between calls")
    fetcher = Fetcher(source, args.max_calls)
    started = time.monotonic()
    fetcher.run(KEYWORDS, args.max_pages)
    fetcher.summary(time.monotonic() - started)
    sys.exit(1 if fetcher.stopped or fetcher.stats["parts"] == 0 else 0)


if __name__ == "__main__":
    main()
