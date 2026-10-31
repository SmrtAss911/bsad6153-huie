"""Digi-Key Product Information API v4 adapter (backup source). NOT YET IMPLEMENTED.

The Digi-Key keys were not in .env when this was written, so only the "not configured"
check exists. To finish it: add DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET to .env, verify
the endpoint, token URL, and paging limits against https://developer.digikey.com, then
implement search() and normalize() the same way mouser.py does.

Terms: https://developer.digikey.com/api-user-agreement (section 5.1(e) forbids building
your own database; section 3.1.4 requires attribution; section 6 suspends for 10 minutes
with 403 Forbidden if you exceed the rate threshold).
"""

import os

from .base import Source, SourceNotConfigured


class DigiKeySource(Source):
    name = "digikey"
    max_page_size = 50  # unverified: check the v4 KeywordSearch docs before relying on it

    @classmethod
    def from_env(cls):
        missing = [name for name in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET")
                   if not os.getenv(name, "").strip()]
        if missing:
            raise SourceNotConfigured(
                "Digi-Key backup is not configured: set " + " and ".join(missing)
                + " in .env, then finish ingest/sources/digikey.py")
        raise SourceNotConfigured(
            "Digi-Key keys are present, but the adapter is not implemented yet: "
            "finish search() and normalize() in ingest/sources/digikey.py")
