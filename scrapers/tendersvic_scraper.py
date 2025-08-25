from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from urllib.parse import urljoin
from dateutil import parser as dateparser
from playwright.sync_api import Page, sync_playwright
import re

BASE = "https://www.tenders.vic.gov.au"

@dataclass
class TendersVICItem:
    platform_type: str
    source: str
    source_url: str
    notice_id: str
    title: str
    agency: Optional[str]
    tender_type: Optional[str]
    status: Optional[str]
    categories: List[str]
    region: Optional[str]
    opened_at: Optional[str]
    closing_at: Optional[str]
    description: Optional[str]

class TendersVICScraper:
    ROW_SEL = 'table.list.tablesaw.tablesaw-stack tbody tr[id^="tenderRow"][data-tender-code]'
    ROW_ANCHOR_SEL = 'table.list.tablesaw.tablesaw-stack tbody tr[id^="tenderRow"] a.strong.tenderRowTitle'

    def __init__(self, page: Optional[Page] = None, headless: bool = True):
        self._external_page = page
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page: Optional[Page] = page
        self._headless = headless

    def __enter__(self):
        if not self._page:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self._headless)
            # Make us look like a real AU browser; extend timeouts a bit
            self._ctx = self._browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
                locale="en-AU",
                timezone_id="Australia/Melbourne",
                viewport={"width": 1366, "height": 900},
            )
            self._page = self._ctx.new_page()
            self._page.set_default_timeout(60000)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._external_page is None:
            try:
                self._ctx and self._ctx.close()
            finally:
                try:
                    self._browser and self._browser.close()
                finally:
                    self._pw and self._pw.stop()

    # ---------- helpers ----------

    def _parse_when(self, s: str) -> Optional[str]:
        try:
            dt = dateparser.parse(s, fuzzy=True)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    @staticmethod
    def _clean(s: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def _text(self, locator) -> str:
        try:
            return self._clean(locator.inner_text())
        except Exception:
            return ""

    def _dismiss_banners(self):
        page = self._page
        assert page
        for sel in ('button:has-text("Accept")', 'button:has-text("OK")', 'button:has-text("I understand")'):
            btn = page.query_selector(sel)
            if btn:
                try:
                    btn.click()
                except Exception:
                    pass

    def _open_listing(self, preset: str):
        page = self._page
        assert page
        def _go(url: str):
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            self._dismiss_banners()
            # rows/anchors may be behind overlays; just ensure they are attached
            try:
                page.wait_for_selector(self.ROW_SEL, state="attached", timeout=60000)
            except Exception:
                page.wait_for_selector(self.ROW_ANCHOR_SEL, state="attached", timeout=60000)
        try:
            _go(f"{BASE}/tender/search2?preset={preset}")
        except Exception:
            _go(f"{BASE}/tender/search?preset={preset}")

    @staticmethod
    def _collect_unspsc_from_listing(text_blob: str) -> List[str]:
        out: List[str] = []
        last = ""
        for raw in text_blob.splitlines():
            line = (raw or "").strip()
            if not line:
                continue
            if re.match(r"(?i)^UNSPSC(\s*\d+)?:", line):
                last = line.split(":", 1)[1].strip()
                if last:
                    out.append(last)
            elif re.match(r"^\d{6,}\s*-", line):  # continuation like "43190000 - Communications ..."
                if out:
                    out[-1] = re.sub(r"\s+", " ", (out[-1] + " " + line).strip())
        return out

    # ---------- scraping ----------

    def fetch_open(self, limit: int = 50, keywords: Optional[List[str]] = None) -> List[TendersVICItem]:
        """Scrape 'Current Tenders' (open). Duplicate this to fetch 'future'/'awarded' if desired."""
        assert self._page, "Scraper not initialized"
        page = self._page

        # Open listing with resilient waits
        self._open_listing("open")

        items: List[Dict[str, Any]] = []
        seen_urls: set = set()

        def collect_from_page():
            for a in page.query_selector_all(self.ROW_ANCHOR_SEL):
                href = a.get_attribute("href") or ""
                if "/tender/view?id=" not in href:
                    continue
                url = urljoin(BASE, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = self._text(a)
                if not title:
                    continue

                # Row-level extraction
                row = a.locator("xpath=ancestor::tr[1]")
                row_code = row.get_attribute("data-tender-code") or ""

                # Status & Type from first cell lines
                c1 = row.locator("td:nth-child(1)")
                status = tender_type = None
                if c1.count():
                    parts = [p for p in self._text(c1).splitlines() if p.strip()]
                    if len(parts) >= 2: status = parts[1]
                    if len(parts) >= 3: tender_type = parts[2]

                # Agency from details cell
                agency = None
                categories_listing: List[str] = []
                c2 = row.locator("td:nth-child(2)")
                if c2.count():
                    for sp in c2.locator(".line-item-detail").all():
                        line = self._text(sp)
                        if line.lower().startswith("issued by:"):
                            agency = line.split(":", 1)[1].strip()
                    categories_listing = self._collect_unspsc_from_listing(self._text(c2))

                # Dates from spans
                opened = closing = None
                od = row.locator("span.opening_date")
                cd = row.locator("span.closing_date")
                if od.count(): opened = self._parse_when(self._text(od))
                if cd.count(): closing = self._parse_when(self._text(cd))

                items.append({
                    "title": title,
                    "url": url,
                    "row_code": (row_code or "").strip(),
                    "agency": agency,
                    "ttype": tender_type,
                    "status": status,
                    "opened": opened,
                    "closing": closing,
                    "categories_listing": categories_listing,
                })
                if len(items) >= limit:
                    break

        # Collect across pages up to limit
        while len(items) < limit:
            collect_from_page()
            if len(items) >= limit:
                break
            # Pagination: link after current page marker (fallback to generic page link)
            nxt = page.query_selector("div.paging .current + a") or \
                  page.query_selector('a[href*="tender/search"][href*="preset="][href*="&page="]:has(span.page)')
            if not nxt:
                break
            nxt.click()
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_selector(self.ROW_ANCHOR_SEL, state="attached", timeout=60000)

        # Enrich from detail pages
        out: List[TendersVICItem] = []
        for it in items[:limit]:
            page.goto(it["url"], wait_until="domcontentloaded")
            page.wait_for_selector("body")

            body = self._text(page.locator("body"))
            m = re.search(r"Display\s+Tender\s+([A-Za-z0-9\-/_. ]+)", body)
            banner_id = self._clean(m.group(1)) if m else ""

            # General details (label->value)
            kv: Dict[str, str] = {}
            for row in page.query_selector_all("#opportunityGeneralDetails .row"):
                lab = self._text(row.query_selector(".weight-bold")) if row else ""
                val = self._text(row.query_selector('.col-sm-9, .col-md-10, div[class*="col-9"], div[class*="col-md-10"]')) if row else ""
                if lab:
                    kv[lab.rstrip(":")] = val

            number  = kv.get("Number") or it.get("row_code") or banner_id
            agency2 = kv.get("Issued By") or it["agency"]
            ttype2  = kv.get("Type") or it["ttype"]
            status2 = kv.get("Status") or it["status"]
            region  = kv.get("Region(s)") or kv.get("Region") or None

            # UNSPSC (detail page; fallback to listing)
            categories: List[str] = []
            unspsc_raw = kv.get("UNSPSC") or ""
            if unspsc_raw:
                categories = [self._clean(x).strip(" -") for x in unspsc_raw.splitlines() if self._clean(x)]
            if not categories:
                categories = it.get("categories_listing") or []

            # Title fallback
            title = it["title"] or ""
            if not title:
                for sel in ("#opportunityDisplayWrapper h1", "#opportunityDisplayWrapper h2", "h1", "h2", "h3"):
                    nodes = page.query_selector_all(sel)
                    for n in nodes:
                        t = self._text(n)
                        if t and not t.lower().startswith("display tender"):
                            title = t; break
                    if title: break

            # Description (first block after header)
            description = None
            try:
                hdr = page.locator("h2, h3", has_text="Description").first
                if hdr:
                    description = self._text(hdr.locator("xpath=following-sibling::*[1]"))
            except Exception:
                pass

            rec = TendersVICItem(
                platform_type="tenders_vic",
                source="Buying for Victoria",
                source_url=it["url"],
                notice_id=number,
                title=title,
                agency=agency2,
                tender_type=ttype2,
                status=status2,
                categories=categories,
                region=region,
                opened_at=it["opened"],
                closing_at=it["closing"],
                description=description,
            )

            if keywords:
                hay = " ".join([rec.title or "", rec.agency or "", " ".join(rec.categories), rec.description or ""]).lower()
                if not any(k.lower() in hay for k in keywords):
                    continue

            out.append(rec)

        return out
