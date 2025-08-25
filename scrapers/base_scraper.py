from __future__ import annotations
# tenderbot/scrapers/base_scraper.py

from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Tender:
    # Required for pipeline identity
    source_portal: str

    # Core identity/metadata
    title: Optional[str] = None
    description: Optional[str] = None
    link: Optional[str] = None

    # Source / external identifier (unified name)
    source_id: Optional[str] = None

    # Back-compat: some old scrapers used atm_id; we map it to source_id
    atm_id: Optional[str] = None

    # Optional metadata for schema
    category: Optional[str] = None
    buyer: Optional[str] = None
    location: Optional[str] = None

    # Dates
    publish_date: Optional[str] = None         # 'YYYY-MM-DD' or ISO date string
    closing_date: Optional[str] = None         # 'YYYY-MM-DD'
    closing_ts: Optional[str] = None           # ISO timestamp string

    # Financials / contacts
    tender_value: Optional[float] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None

    def __post_init__(self):
        # Map old field to new unified name
        if not self.source_id and self.atm_id:
            self.source_id = self.atm_id

        # If only closing_ts is provided, derive closing_date (YYYY-MM-DD)
        if not self.closing_date and self.closing_ts:
            # accept ISO strings like 'YYYY-MM-DDTHH:MM:SSZ'
            if len(self.closing_ts) >= 10:
                self.closing_date = self.closing_ts[:10]

    def to_row(self) -> dict:
        """
        Convert to a dict aligned with the DB schema / TENDER_COLUMNS.
        (Embedding is computed later; keep it None here.)
        """
        return {
            "source_portal": self.source_portal,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "buyer": self.buyer,
            "location": self.location,
            "publish_date": self.publish_date,
            "closing_date": self.closing_date,
            "closing_ts": self.closing_ts,
            "tender_value": self.tender_value,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "link": self.link,
            "embedding": None,   # filled after insertion
            # tender_hash is set by the orchestrator before DB upsert
        }

class BaseScraper:
    name: str = "base"

    async def fetch(self) -> List[Tender]:
        """
        Return a list of Tender instances for this source.
        Concrete scrapers must implement this.
        """
        raise NotImplementedError

