
import re
from urllib.parse import urljoin, urlencode, urlparse, parse_qs
from playwright.async_api import async_playwright
from .base_scraper import BaseScraper, Tender
from utils.helpers import parse_date_safe
from utils.config import Config

BASE = "https://www.tenders.gov.au"
LIST = f"{BASE}/atm"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

class AusTenderScraper(BaseScraper):
    name = "austender"

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg

    async def fetch(self):
        import asyncio
        items = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            try:
                ctx = await browser.new_context(
                    user_agent=UA, locale="en-AU",
                    extra_http_headers={"Accept-Language":"en-AU,en;q=0.9","Referer":BASE+"/"}
                )
                page = await ctx.new_page()
                # Per-action timeouts: conservative but not huge
                page.set_default_timeout(8000)
                page.set_default_navigation_timeout(15000)

                items_per_page = getattr(self.cfg, "items_per_page", 100) if self.cfg else 100
                max_items = getattr(self.cfg, "max_items_per_portal", 400) if self.cfg else 400

                start_url = f"{LIST}?{urlencode({'ItemsPerPage': items_per_page, 'AtmPage': 1})}"
                await page.goto(start_url, wait_until="networkidle")
                await page.wait_for_selector(".boxEQH", timeout=20000)

                total = 0
                while True:
                    batch = await self._scrape_page(page, already=total, max_items=max_items)
                    items.extend(batch)
                    total += len(batch)
                    if total >= max_items:
                        break

                    next_href = await self._get_next_href(page)
                    if not next_href:
                        break

                    # keep ItemsPerPage high across pages
                    parsed = urlparse(next_href)
                    q = parse_qs(parsed.query)
                    q["ItemsPerPage"] = [str(items_per_page)]
                    next_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode({k: v[0] for k, v in q.items()})}"

                    await page.goto(next_url, wait_until="networkidle")
                    await page.wait_for_selector(".boxEQH", timeout=20000)

            except asyncio.CancelledError:
                # Outer timeout hit; close browser cleanly and re-raise
                try: await browser.close()
                except: pass
                raise
            finally:
                try: await browser.close()
                except: pass

        return items

    async def _scrape_page(self, page, already: int, max_items: int):
        rows = await page.query_selector_all(".boxEQH .row")
        out = []
        for row in rows:
            if len(out) + already >= max_items:
                break
            left  = await row.query_selector(".col-sm-4")
            right = await row.query_selector(".col-sm-8")
            if not right:
                continue

            title = _clean(await left.inner_text()) if left else ""

            fields = {"ATM ID":"","Close Date & Time":"","Agency":"","Category":"","Description":""}
            for blk in await right.query_selector_all(".list-desc"):
                t = _clean(await blk.inner_text())
                for k in fields:
                    if t.lower().startswith(k.lower()):
                        fields[k] = t.split(":", 1)[-1].strip()

            # Prefer the ATM ID link; fallback to 'Full Details'
            link_el = await right.query_selector(".list-desc a") or await right.query_selector("a:has-text('Full Details')")
            link = await link_el.get_attribute("href") if link_el else ""
            if link.startswith("/"):
                link = urljoin(BASE, link)

            out.append(Tender(
                title=title,
                description=fields["Description"],
                category=fields["Category"],
                closing_date=parse_date_safe(fields["Close Date & Time"]),
                buyer=fields["Agency"],
                link=link,
                contact_name=None,
                contact_email=None,
                tender_value=None,
                source_portal=self.name,
            ))
        return out

    async def _get_next_href(self, page):
        a = page.locator("ul.pagination li.next a")
        if await a.count() == 0:
            return None
        href = await a.first.get_attribute("href")
        return urljoin(LIST, href) if href else None
