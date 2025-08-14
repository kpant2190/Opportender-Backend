from .base_scraper import BaseScraper, Tender
import datetime as dt

class StaticExampleFeed(BaseScraper):
    name = "static-example"
    async def fetch(self):
        today = dt.date.today()
        return [
            Tender(
                title="Managed IT Services for Regional Office",
                description="Seeking managed services for network monitoring, helpdesk, and cybersecurity.",
                category="IT Services",
                closing_date=str(today + dt.timedelta(days=21)),
                buyer="Example Council",
                link="https://example.org/tenders/managed-it",
                contact_name="Procurement Team",
                contact_email="procurement@example.org",
                tender_value=None,
                source_portal=self.name,
            ),
            Tender(
                title="Cloud Migration and ERP Integration",
                description="Migrate on-prem workloads to AWS/Azure and integrate with existing ERP.",
                category="Cloud / ERP",
                closing_date=str(today + dt.timedelta(days=28)),
                buyer="Example Health",
                link="https://example.org/tenders/cloud-erp",
                contact_name="IT Buyer",
                contact_email="itbuyer@example.org",
                tender_value=None,
                source_portal=self.name,
            ),
        ]
