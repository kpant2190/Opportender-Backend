from __future__ import annotations
# tenderbot/scrapers/austender_scraper.py

import re
from urllib.parse import urljoin, urlencode, urlparse, parse_qs
from playwright.async_api import async_playwright
from .base_scraper import BaseScraper, Tender
# If you run with `python -m tenderbot.tenderbot`, use the package-qualified path:
from tenderbot.utils.helpers import parse_date_safe
from tenderbot.utils.config import Config

BASE = "https://www.tenders.gov.au"
LIST = f"{BASE}/atm"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _kv_lines_to_fields(lines: list[str]) -> dict[str, str]:
    """
    Convert lines like 'ATM ID: ABC123' to a dict. Case-insensitive keys.
    Known keys we try to capture: ATM ID, Close Date & Time, Agency, Category, Description,
    Publish Date, Location, Value (rare).
    """
    fields: dict[str, str] = {}
    for raw in lines:
        t = _clean(raw)
        if not t or ":" not in t:
            continue
        k, v = t.split(":", 1)
        fields[k.strip().lower()] = v.strip()
    return fields

def _first_or_none(text: str | None) -> str | None:
    t = _clean(text or "")
    return t or None

class AusTenderScraper(BaseScraper):
    name = "austender"

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg

    async def fetch(self):
        import asyncio
        items = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            try:
                ctx = await browser.new_context(
                    user_agent=UA,
                    locale="en-AU",
                    extra_http_headers={
                        "Accept-Language": "en-AU,en;q=0.9",
                        "Referer": BASE + "/",
                        "Cache-Control": "no-cache",
                    }
                )

                # Speed up by dropping images/fonts/media
                async def _route(route, request):
                    rt = request.resource_type
                    if rt in ("image", "media", "font"):
                        return await route.abort()
                    return await route.continue_()
                await ctx.route("**/*", _route)

                page = await ctx.new_page()
                page.set_default_timeout(12000)              # per-action
                page.set_default_navigation_timeout(30000)   # per-nav

                max_items = getattr(self.cfg, "max_items_per_portal", 400) if self.cfg else 400

                # Try large page first, then fall back if slow
                for per_page in (getattr(self.cfg, "items_per_page", 100) if self.cfg else 100, 50, 25):
                    try:
                        start_url = f"{LIST}?{urlencode({'ItemsPerPage': per_page, 'AtmPage': 1})}"
                        await page.goto(start_url, wait_until="domcontentloaded")
                        await page.wait_for_selector(".boxEQH", state="attached", timeout=20000)
                        break
                    except Exception:
                        # try smaller per_page
                        continue

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

                    parsed = urlparse(next_href)
                    q = parse_qs(parsed.query)
                    # keep the current per_page if present, else force to 50 (stable)
                    q["ItemsPerPage"] = [q.get("ItemsPerPage", [str(per_page)])[0]]
                    next_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode({k: v[0] for k, v in q.items()})}"

                    await page.goto(next_url, wait_until="domcontentloaded")
                    await page.wait_for_selector(".boxEQH", state="attached", timeout=20000)

            except asyncio.CancelledError:
                try:
                    await browser.close()
                except:
                    pass
                raise
            finally:
                try:
                    await browser.close()
                except:
                    pass

        return items

    async def _scrape_page(self, page, already: int, max_items: int):
        rows = await page.query_selector_all(".boxEQH .row")
        out: list[Tender] = []

        for row in rows:
            if len(out) + already >= max_items:
                break

            left = await row.query_selector(".col-sm-4")    # title container
            right = await row.query_selector(".col-sm-8")   # meta container
            if not right:
                continue

            title = _first_or_none(await left.inner_text()) if left else None

            # Collect meta lines from the right block
            meta_lines: list[str] = []
            for blk in await right.query_selector_all(".list-desc"):
                t = await blk.inner_text()
                if t:
                    meta_lines.append(t)

            f = _kv_lines_to_fields(meta_lines)
            # Normalise keys we care about
            atm_id        = f.get("atm id")
            close_str     = f.get("close date & time") or f.get("close date") or f.get("closing date")  # be flexible
            agency        = f.get("agency")
            category      = f.get("category")
            description   = f.get("description")
            publish_str   = f.get("publish date")
            location      = f.get("location")
            value_str     = f.get("value")  # rarely present

            # Prefer the ATM ID link; fallback to 'Full Details'
            link_el = await right.query_selector(".list-desc a") or await right.query_selector("a:has-text('Full Details')")
            link = await link_el.get_attribute("href") if link_el else ""
            if link and link.startswith("/"):
                link = urljoin(BASE, link)
            link = link or None

            # Derive source_id if not explicitly present
            source_id = _first_or_none(atm_id)
            if not source_id and link:
                # Try to extract something ATM-like from the URL if available
                m = re.search(r"/atm/[^/]+/[^/]+/([^/?#]+)", link, re.I)
                if m:
                    source_id = m.group(1)

            # Dates: we support both date-only and timestamp with parse_date_safe
            closing_ts = parse_date_safe(close_str) if close_str else None
            publish_date = parse_date_safe(publish_str) if publish_str else None

            # Keep both closing_date (date) and closing_ts (full ts) for the unified schema
            closing_date = closing_ts[:10] if closing_ts else None

            # Optional: parse numeric value if present (very rare on list page)
            tender_value = None
            if value_str:
                # naive numeric pick-up; your normalizer can improve this if needed
                m = re.search(r"([\d,]+(?:\.\d{1,2})?)", value_str.replace(",", ""))
                if m:
                    try:
                        tender_value = float(m.group(1))
                    except:
                        pass

            # If list description is empty and we have a link, we could fetch details page.
            # (kept simple; the central relevance filter handles long text/embeddings)
            desc = _first_or_none(description)

            out.append(Tender(
                source_portal=self.name,
                source_id=source_id,
                title=title,
                description=desc,
                category=_first_or_none(category),
                buyer=_first_or_none(agency),
                location=_first_or_none(location),
                publish_date=publish_date,         # ISO string or None
                closing_date=closing_date,         # 'YYYY-MM-DD' or None
                closing_ts=closing_ts,             # ISO string or None
                tender_value=tender_value,
                contact_name=None,
                contact_email=None,
                link=link,
            ))

        return out

    async def _get_next_href(self, page):
        a = page.locator("ul.pagination li.next a")
        if await a.count() == 0:
            return None
        href = await a.first.get_attribute("href")
        return urljoin(LIST, href) if href else None

