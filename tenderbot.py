from __future__ import annotations
def to_db_row(t):
    row = t.to_row()
    row.setdefault("source_portal", getattr(t, "source_portal", None))
    row.setdefault("link", getattr(t, "link", None))
    row.setdefault("source_id", getattr(t, "source_id", None))
    row.setdefault("atm_id", getattr(t, "atm_id", None))
    row.setdefault("location", getattr(t, "location", None))
    row.setdefault("publish_date", getattr(t, "publish_date", None))
    row.setdefault("closing_ts", getattr(t, "closing_ts", None))
    row["tender_hash"] = row_hash(row)
    row.setdefault("embedding", None)
    return row
# tenderbot/tenderbot.py

import os
import asyncio
import random
import argparse
from asyncio import TimeoutError
from typing import Any, Dict, List

from tenderbot.utils.config import Config
from tenderbot.utils.logger import logger
from tenderbot.utils.helpers import row_hash
from tenderbot.services.db import DB
from tenderbot.services.embedder import Embedder
from tenderbot.services.relevance_filter import RelevanceFilter
from tenderbot.services.notifier import Notifier
from tenderbot.services.crm import CRM

from tenderbot.scrapers.base_scraper import Tender as TenderDC
from tenderbot.scrapers import SCRAPERS


# ------------------------ helpers ------------------------

def ensure_tender(obj: Any) -> TenderDC:
    """
    Accept either a Tender dataclass or a dict and return a Tender instance.
    Ensures 'source_id' is present (maps from 'atm_id' if provided).
    """
    if isinstance(obj, TenderDC):
        return obj
    if isinstance(obj, dict):
        # Map legacy keys if needed
        src_id = obj.get("source_id") or obj.get("atm_id")
        return TenderDC(
            source_portal=obj.get("source_portal") or "unknown",
            title=obj.get("title"),
            link=obj.get("link"),
            source_id=src_id,
            description=obj.get("description"),
            category=obj.get("category"),
            buyer=obj.get("buyer"),
            location=obj.get("location"),
            publish_date=obj.get("publish_date"),
            closing_date=obj.get("closing_date"),
            closing_ts=obj.get("closing_ts"),
            tender_value=obj.get("tender_value"),
            contact_name=obj.get("contact_name"),
            contact_email=obj.get("contact_email"),
        )
    raise TypeError(f"Unsupported tender type: {type(obj)}")


def _timeout_for(scraper_name: str, cfg: Config) -> int:
    overrides = {
        "austender": int(os.getenv("TIMEOUT_AUSTENDER", "0")),
        "qtenders": int(os.getenv("TIMEOUT_QTENDERS", "0")),
        "tendersvic": int(os.getenv("TIMEOUT_TENDERSVIC", "0")),
        "static-example": int(os.getenv("TIMEOUT_STATIC_EXAMPLE", "0")),
    }
    return overrides.get(scraper_name, 0) or cfg.scraper_timeout_seconds


async def _run_with_retries(scraper, cfg: Config) -> List[TenderDC]:
    """Run a scraper with per-scraper timeout + retries. Always returns a list."""
    attempts = 1 + max(0, cfg.retry_attempts)  # total tries
    for i in range(1, attempts + 1):
        try:
            timeout = _timeout_for(scraper.name, cfg)
            result = await asyncio.wait_for(scraper.fetch(), timeout=timeout)
            # Coerce to Tender instances
            return [ensure_tender(x) for x in (result or [])]
        except TimeoutError:
            logger.error(f"Scraper {scraper.name} timed out after {timeout}s (try {i}/{attempts})")
        except Exception as e:
            logger.error(f"Scraper {scraper.name} failed (try {i}/{attempts}): {e}")

        if i < attempts:
            # exponential backoff + jitter
            base = max(1, cfg.retry_backoff_base)
            delay = base * (2 ** (i - 1))
            jitter = random.randint(0, max(0, cfg.retry_jitter_ms)) / 1000.0
            sleep_for = delay + jitter
            logger.info(f"Retrying {scraper.name} in {sleep_for:.1f}s...")
            await asyncio.sleep(sleep_for)

    logger.error(f"Scraper {scraper.name} exhausted retries; continuing.")
    return []


# ------------------------ main bot ------------------------

class TenderBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = DB(cfg)
        self.embedder = Embedder(cfg)
        self.relevance = RelevanceFilter(cfg, self.embedder)
        self.notifier = Notifier(cfg)
        self.crm = CRM(cfg)

        # Enable/disable scrapers here - can be overridden by SCRAPERS_TO_RUN env var
        default_scrapers = ["static_example", "austender", "qtenders"]
        scrapers_to_run = os.getenv("SCRAPERS_TO_RUN", "").strip()
        if scrapers_to_run:
            default_scrapers = [s.strip() for s in scrapers_to_run.split(",") if s.strip()]
        
        self.scrapers = []
        for scraper_name in default_scrapers:
            if scraper_name in SCRAPERS:
                scraper_class = SCRAPERS[scraper_name]
                # Some scrapers need config, others don't
                if scraper_name in ["austender", "qtenders"]:
                    self.scrapers.append(scraper_class(cfg))
                else:
                    self.scrapers.append(scraper_class())
            else:
                logger.warning(f"Unknown scraper: {scraper_name}")

        # Log dataclass fields once for visibility
        fields = {f.name: f.type for f in TenderDC.__dataclass_fields__.values()}  # type: ignore
        logger.info(f"Tender fields: {fields}")

    async def run_once(self):
        all_rows: List[dict] = []
        total_found = skipped_kw = skipped_sim = 0

        # 1) Scrape + relevance filter
        for s in self.scrapers:
            logger.info(f"Scraping: {s.name}")
            tenders = await _run_with_retries(s, self.cfg)
            total_found += len(tenders)

            for t in tenders:
                # quick keyword check (for stats only; RelevanceFilter decides)
                hay = f"{(t.title or '')}\n{(t.description or '')}".lower()
                kw_hit = any(k in hay for k in self.cfg.keywords)

                if not self.relevance.is_relevant(t):
                    if not kw_hit:
                        skipped_kw += 1
                    else:
                        skipped_sim += 1
                    continue

                row = to_db_row(t)
                all_rows.append(row)

        if not all_rows:
            logger.info(
                f"Run complete. Found: {total_found} | Upserted: 0 | "
                f"Skipped(relevance_kw): {skipped_kw} | Skipped(relevance_sim): {skipped_sim}"
            )
            return

        # 2) Batch upsert (RPC w/ fallback handled inside DB)
        inserted = self.db.upsert_tenders_return_inserted(all_rows)

        # 3) Embed + update + notify + CRM for newly inserted only
        inserted_hashes = set()
        if isinstance(inserted, list):
            for d in inserted:
                h = d.get("tender_hash")
                if h:
                    inserted_hashes.add(h)
        elif isinstance(inserted, set):
            inserted_hashes = inserted

        inserted_rows = [r for r in all_rows if r["tender_hash"] in inserted_hashes]
        for r in inserted_rows:
            text = f"{r.get('title','')} {r.get('description','')}".strip()
            vec = self.embedder.embed(text)
            if vec:
                self.db.update_embedding(r, vec)
            # Notify + mark notified
            self.notifier.notify_tender(r)
            self.db.set_notified_at(r["tender_hash"])
            # CRM push (optional)
            self.crm.push(r)

        logger.info(
            f"Run complete. Found: {total_found} | Upserted: {len(inserted_rows)} | "
            f"Skipped(relevance_kw): {skipped_kw} | Skipped(relevance_sim): {skipped_sim}"
        )


# ------------------------ CLI loop ------------------------

async def _loop(bot: TenderBot, seconds: int):
    if seconds <= 0:
        await bot.run_once()
        return
    while True:
        await bot.run_once()
        await asyncio.sleep(seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-db", action="store_true", help="Check/create DB objects (non-destructive).")
    parser.add_argument("--loop", type=int, default=0, help="Run continuously every N seconds (0 = once).")
    args = parser.parse_args()

    cfg = Config.load()
    bot = TenderBot(cfg)
    if args.init_db:
        bot.db.init()
    asyncio.run(_loop(bot, args.loop))


