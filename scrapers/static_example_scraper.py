from __future__ import annotations
# tenderbot/scrapers/static_example_scraper.py

from .base_scraper import BaseScraper, Tender
from datetime import date, datetime, timedelta, timezone

class StaticExampleFeed(BaseScraper):
    name = "static_example"  # keep snake_case like other portals

    async def fetch(self):
        today = date.today()
        publish_date = today.isoformat()

        def make_close(days_from_now: int):
            # Close at 17:00 UTC for demo; Tender.__post_init__ will derive closing_date (YYYY-MM-DD)
            dt_close = datetime.combine(today + timedelta(days=days_from_now), datetime.min.time()).replace(hour=17, tzinfo=timezone.utc)
            return dt_close.isoformat()

        return [
            Tender(
                source_portal=self.name,
                source_id="EX-IT-001",
                title="Managed IT Services for Regional Office",
                description="Seeking managed services for network monitoring, helpdesk, and cybersecurity.",
                category="IT Services",
                buyer="Example Council",
                location="Australia",
                publish_date=publish_date,
                closing_ts=make_close(21),
                tender_value=None,
                contact_name="Procurement Team",
                contact_email="procurement@example.org",
                link="https://example.org/tenders/managed-it",
            ),
            Tender(
                source_portal=self.name,
                source_id="EX-CLD-002",
                title="Cloud Migration and ERP Integration",
                description="Migrate on-prem workloads to AWS/Azure and integrate with existing ERP.",
                category="Cloud / ERP",
                buyer="Example Health",
                location="Australia",
                publish_date=publish_date,
                closing_ts=make_close(28),
                tender_value=None,
                contact_name="IT Buyer",
                contact_email="itbuyer@example.org",
                link="https://example.org/tenders/cloud-erp",
            ),
        ]

