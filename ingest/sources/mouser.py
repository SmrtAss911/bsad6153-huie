"""Mouser Search API adapter (primary source).

Docs:  https://www.mouser.com/en/api-search/   Spec: https://api.mouser.com/api/docs/v1
Terms: https://www.mouser.com/en/apiterms/ (section 4 restricts storing data; see docs/data_dictionary.md)

The API key goes in the URL's query string (?apiKey=...), so this file never logs a URL
or a requests exception's text, because both would contain the key.
"""

import os
import re

import requests

from .base import (AccessDenied, BadResponse, PartRecord, RateLimited, SearchPage,
                   Source, SourceNotConfigured, TransientError)

KEYWORD_URL = "https://api.mouser.com/api/v1/search/keyword"
TIMEOUT = (10, 30)  # seconds to connect, seconds to wait for the answer

# Words we treat as "you called too often" if they appear in Mouser's Errors list.
# Mouser does not document its limit message, so this is a best guess. Check the logs.
LIMIT_WORDS = ("limit", "exceed", "too many")


def _to_int(value):
    """'1,234' or '1234' -> 1234; anything without digits -> None. Only for counts."""
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def _to_price(text):
    """'$1,234.56' -> 1234.56; anything we can't read -> None (the raw JSON keeps the text)."""
    if not text:
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(text)))
    except ValueError:
        return None


def _text(value):
    """Mouser sometimes sends the string "None" instead of leaving a field out; treat it as missing."""
    if value is None or str(value).strip() in ("", "None"):
        return None
    return value


class MouserSource(Source):
    name = "mouser"
    max_page_size = 50  # "Up to 50 results returned per call" (api-search page)

    def __init__(self, api_key):
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    @classmethod
    def from_env(cls):
        key = os.getenv("MOUSER_API_KEY", "").strip()
        if not key:
            raise SourceNotConfigured("MOUSER_API_KEY is not set in .env")
        return cls(key)

    def _mask(self, text):
        """Replace the key with *** in anything we might save or print."""
        return str(text).replace(self._api_key, "***") if text else text

    def search(self, query, offset, limit):
        body = {"SearchByKeywordRequest": {
            "keyword": query,
            "records": min(limit, self.max_page_size),
            "startingRecord": offset,
        }}
        try:
            resp = self._session.post(KEYWORD_URL, params={"apiKey": self._api_key},
                                      json=body, timeout=TIMEOUT)
        except requests.Timeout:
            raise TransientError("timeout") from None
        except requests.RequestException as exc:
            # Class name only: the exception's message includes the URL, and the URL has the key.
            raise TransientError(f"network error ({type(exc).__name__})") from None

        status = resp.status_code
        text = self._mask(resp.text)
        if status == 429:
            raise RateLimited("HTTP 429")
        if status in (401, 403):
            raise AccessDenied(f"HTTP {status}")
        if status >= 500:
            raise TransientError(f"HTTP {status}")
        if status != 200:
            raise BadResponse(f"HTTP {status}", status, text)

        try:
            data = resp.json()
        except ValueError:
            raise BadResponse("response is not JSON", status, text) from None
        if not isinstance(data, dict):
            raise BadResponse("response JSON is not an object", status, text)

        # Mouser can answer HTTP 200 and still put a problem in its Errors list.
        errors = data.get("Errors") or []
        if errors:
            messages = self._mask("; ".join(
                str(e.get("Message") or e.get("Code") or e) if isinstance(e, dict) else str(e)
                for e in errors))
            lowered = messages.lower()
            if any(word in lowered for word in LIMIT_WORDS):
                raise RateLimited(f"Errors: {messages}")
            if "key" in lowered:
                raise AccessDenied(f"Errors: {messages}")
            raise BadResponse(f"Errors: {messages}", status, text)

        results = data.get("SearchResults")
        if not isinstance(results, dict) or not isinstance(results.get("Parts"), list):
            raise BadResponse("no SearchResults.Parts in response", status, text)
        return SearchPage(raw=data, http_status=status,
                          total=_to_int(results.get("NumberOfResult")), parts=results["Parts"])

    def normalize(self, raw_part):
        part_number = raw_part.get("MouserPartNumber")
        if not part_number:
            raise BadResponse("part has no MouserPartNumber", body=raw_part)
        price_breaks = [
            {"quantity": _to_int(pb.get("Quantity")), "price": _to_price(pb.get("Price")),
             "currency": pb.get("Currency")}
            for pb in raw_part.get("PriceBreaks") or [] if isinstance(pb, dict)
        ]
        attributes = [
            {"name": a.get("AttributeName"), "value": a.get("AttributeValue")}
            for a in raw_part.get("ProductAttributes") or [] if isinstance(a, dict)
        ]
        return PartRecord(
            source=self.name,
            source_part_number=part_number,
            manufacturer=raw_part.get("Manufacturer"),
            manufacturer_part_number=raw_part.get("ManufacturerPartNumber"),
            description=raw_part.get("Description"),
            category=raw_part.get("Category"),
            availability_text=_text(raw_part.get("Availability")),
            in_stock_qty=_to_int(raw_part.get("AvailabilityInStock")),
            lead_time=raw_part.get("LeadTime"),
            lifecycle_status=raw_part.get("LifecycleStatus"),
            min_order_qty=_to_int(raw_part.get("Min")),
            order_multiple=_to_int(raw_part.get("Mult")),
            product_url=raw_part.get("ProductDetailUrl"),
            price_breaks=price_breaks,
            attributes=attributes,
        )
