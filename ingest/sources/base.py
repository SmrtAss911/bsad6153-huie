"""The interface every part-data source implements, so fetch.py never needs to know
which API it is talking to. Mouser is the primary source; Digi-Key is the backup.
"""

from dataclasses import dataclass, field


# Errors a source raises. fetch.py decides what to do with each one (retry, skip, or stop).

class SourceNotConfigured(Exception):
    """The keys for this source are not in .env."""


class AccessDenied(Exception):
    """HTTP 401/403. On the first call this means a bad key; later it can mean a limit."""


class RateLimited(Exception):
    """HTTP 429, or the API said in its Errors list that we called too often."""


class TransientError(Exception):
    """A timeout, connection error, or 5xx. Worth retrying."""


class BadResponse(Exception):
    """The API answered, but not with something we can use. Not worth retrying."""

    def __init__(self, message, http_status=None, body=None):
        super().__init__(message)
        self.http_status = http_status
        self.body = body  # saved to data/raw/ so we can see what went wrong


@dataclass
class SearchPage:
    """One API call's result: the raw JSON (saved as-is) plus the parts list inside it."""
    raw: dict
    http_status: int
    total: int | None          # how many results the API says exist for this query
    parts: list[dict]          # the raw part dicts, not yet normalized


@dataclass
class PartRecord:
    """One part in a shape every source can fill. Fields a source lacks stay None."""
    source: str
    source_part_number: str
    manufacturer: str | None
    manufacturer_part_number: str | None
    description: str | None
    category: str | None
    availability_text: str | None   # e.g. "1,234 In Stock", kept exactly as the API sent it
    in_stock_qty: int | None
    lead_time: str | None
    lifecycle_status: str | None
    min_order_qty: int | None
    order_multiple: int | None
    product_url: str | None
    price_breaks: list[dict] = field(default_factory=list)  # [{"quantity", "price", "currency"}]
    attributes: list[dict] = field(default_factory=list)    # [{"name", "value"}]


class Source:
    """Base class. A source sets name and max_page_size and implements the three methods."""
    name = "base"
    max_page_size = 50

    @classmethod
    def from_env(cls):
        """Build the source from .env values, or raise SourceNotConfigured."""
        raise NotImplementedError

    def search(self, query, offset, limit):
        """Run one keyword search call and return a SearchPage."""
        raise NotImplementedError

    def normalize(self, raw_part):
        """Turn one raw part dict into a PartRecord."""
        raise NotImplementedError
