from playwright.async_api import async_playwright
from .base_scraper import BaseScraper, Tender
from utils.helpers import parse_date_safe

class TendersVICScraper(BaseScraper):
    name = "tendersvic"

    async def fetch(self):
        out = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            page.set_default_timeout(6000)
            page.set_default_navigation_timeout(8000)
            await page.goto("https://www.tenders.vic.gov.au/", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector("table, .results, .search-results", timeout=6000)
                rows = await page.query_selector_all("tbody tr")
                for r in rows[:25]:
                    cols = await r.query_selector_all("td")
                    texts = [await c.inner_text() for c in cols]
                    link_el = await r.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else None
                    title = texts[0].strip() if texts else ""
                    buyer = texts[1].strip() if len(texts) > 1 else None
                    closing = texts[-1].strip() if texts else None
                    link = href or ""
                    out.append(Tender(
                        title=title,
                        description=title,
                        category=None,
                        closing_date=parse_date_safe(closing),
                        buyer=buyer,
                        link=link,
                        contact_name=None,
                        contact_email=None,
                        tender_value=None,
                        source_portal=self.name,
                    ))
            finally:
                await browser.close()
        return out
