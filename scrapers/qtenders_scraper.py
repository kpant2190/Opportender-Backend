from __future__ import annotations
# tenderbot/scrapers/qtenders_scraper.py
import re
from urllib.parse import urljoin
from playwright.async_api import async_playwright
from .base_scraper import BaseScraper, Tender
from tenderbot.utils.helpers import parse_date_safe
from tenderbot.utils.config import Config

BASE = "https://qtenders.epw.qld.gov.au"
START = f"{BASE}/qtenders/tender/search/tender-search.do?action=advanced-tender-search-open-tender"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _extract_date(text: str | None) -> str | None:
    """
    QTenders closing text looks like: '12:00 PM , 25 Aug, 2025'
    We pull the '25 Aug, 2025' bit and normalize.
    """
    if not text:
        return None
    m = re.search(r"(\d{1,2}\s+[A-Za-z]{3},?\s+\d{4})", text)
    if not m:
        return None
    date_part = m.group(1).replace(",", "")
    return parse_date_safe(date_part)

class QTendersScraper(BaseScraper):
    name = "qtenders"

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg

    async def fetch(self):
        out = []
        max_items = getattr(self.cfg, "max_items_per_portal", 50) if self.cfg else 50

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            ctx = await browser.new_context(
                user_agent=UA,
                locale="en-AU",
                extra_http_headers={"Accept-Language":"en-AU,en;q=0.9","Referer":BASE+"/"},
            )
            page = await ctx.new_page()
            page.set_default_timeout(12000)
            page.set_default_navigation_timeout(20000)

            await page.goto(START, wait_until="domcontentloaded")

            # Wait until we have either a results row or the pager
            await page.wait_for_selector("table.paging, tr:has(a#MSG)", timeout=20000)

            current_page = 1
            while len(out) < max_items:
                # Scrape one page
                rows = await page.query_selector_all("tr:has(a#MSG), tr[bgcolor='#E7E7E6'], tr[bgcolor='#F6F6F6']")
                for row in rows:
                    if len(out) >= max_items:
                        break

                    # Title + link
                    a = await row.query_selector("a#MSG")
                    if not a:
                        continue
                    title = _clean(await a.inner_text())
                    href = await a.get_attribute("href")
                    link = urljoin(BASE, href) if href else ""

                    # 'Issued by ...' and 'UNSPSC: ...' sit in SUMMARY_SMALL
                    summary_el = await row.query_selector("span.SUMMARY_SMALL")
                    summary = _clean(await summary_el.inner_text()) if summary_el else ""
                    buyer = None
                    category = None
                    if "Issued by" in summary:
                        m = re.search(r"Issued by\s+(.*?)(?:\s+UNSPSC:|$)", summary, flags=re.I)
                        if m:
                            buyer = _clean(m.group(1))
                    if "UNSPSC:" in summary:
                        m = re.search(r"UNSPSC:\s*(.*)$", summary, flags=re.I)
                        if m:
                            # keep full UNSPSC line as category text
                            category = _clean(m.group(1))

                    # closing date (there can be multiple SUMMARY_CLOSINGDATE spans; pick the last non-empty)
                    closers = await row.query_selector_all("span.SUMMARY_CLOSINGDATE")
                    closing_raw = None
                    for el in closers:
                        txt = _clean(await el.inner_text())
                        if txt:
                            closing_raw = txt
                    closing_date = _extract_date(closing_raw)

                    # tender number/code (e.g., VP466467) usually in the first <td> bold
                    code = None
                    first_td = await row.query_selector("td[align='left'] b")
                    if first_td:
                        maybe = _clean(await first_td.inner_text())
                        if re.match(r"^[A-Z]{1,3}\d{4,}$", maybe):
                            code = maybe

                    out.append(Tender(
                        title=title,
                        description=title,        # no list description; details page has full text if needed
                        category=category,
                        closing_date=closing_date,
                        buyer=buyer,
                        link=link,
                        contact_name=None,
                        contact_email=None,
                        tender_value=None,
                        source_portal=self.name,
                        atm_id=code,              # store the VP/number here for now
                    ))

                # Stop if we met the limit
                if len(out) >= max_items:
                    break

                # Try to go to the next page via the numeric pager
                # Read current hidden page value; if missing, assume current_page
                try:
                    hidden_val = await page.eval_on_selector('input[name="page"]', "el => el && el.value")
                    if hidden_val and str(hidden_val).isdigit():
                        current_page = int(hidden_val)
                except Exception:
                    pass

                next_label = str(current_page + 1)
                next_link = page.locator(f'table.paging a:has-text("{next_label}")')
                if await next_link.count() == 0:
                    break  # no next page
                
                # click next page and wait for navigation
                async with page.expect_navigation(wait_until="domcontentloaded"):
                    await next_link.first.click()
                
                # wait until rows exist before querying them
                await page.wait_for_selector(
                    "tr[bgcolor='#E7E7E6'], tr[bgcolor='#F6F6F6'], tr:has(a#MSG)",
                    timeout=15000
                )

            await browser.close()

        return out

