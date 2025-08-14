

import os, asyncio, random
import argparse
from asyncio import TimeoutError
from utils.config import Config
from utils.logger import logger
from utils.helpers import row_hash
from services.db import DB
from services.embedder import Embedder
from services.relevance_filter import RelevanceFilter
from services.notifier import Notifier
from services.crm import CRM
from scrapers.static_example_scraper import StaticExampleFeed
from scrapers.austender_scraper import AusTenderScraper
from scrapers.qtenders_scraper import QTendersScraper
from scrapers.tendersvic_scraper import TendersVICScraper

class TenderBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = DB(cfg)
        self.embedder = Embedder(cfg)
        self.relevance = RelevanceFilter(cfg, self.embedder)
        self.notifier = Notifier(cfg)
        self.crm = CRM(cfg)
        self.scrapers = [
            StaticExampleFeed(),
            AusTenderScraper(cfg),
            # QTendersScraper(),          # temporarily disabled
            # TendersVICScraper(),        # temporarily disabled
        ]

    def _timeout_for(self, scraper_name: str):
        import os
        overrides = {
            "austender": int(os.getenv("TIMEOUT_AUSTENDER", "0")),
            "qtenders": int(os.getenv("TIMEOUT_QTENDERS", "0")),
            "tendersvic": int(os.getenv("TIMEOUT_TENDERSVIC", "0")),
        }
        return overrides.get(scraper_name, 0) or self.cfg.scraper_timeout_seconds

    async def run_once(self):
        def _timeout_for(scraper_name: str, cfg):
            overrides = {
                "austender": int(os.getenv("TIMEOUT_AUSTENDER", "0")),
                "qtenders": int(os.getenv("TIMEOUT_QTENDERS", "0")),
                "tendersvic": int(os.getenv("TIMEOUT_TENDERSVIC", "0")),
            }
            return overrides.get(scraper_name, 0) or cfg.scraper_timeout_seconds

        async def _run_with_retries(scraper, cfg):
            """Run a scraper with per-scraper timeout + retries. Returns list of tenders or []."""
            attempts = 1 + max(0, cfg.retry_attempts)  # total tries
            for i in range(1, attempts + 1):
                try:
                    timeout = _timeout_for(scraper.name, cfg)
                    return await asyncio.wait_for(scraper.fetch(), timeout=timeout)
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

        total_found = total_new = skipped_kw = skipped_sim = skipped_dupe = 0

        for s in self.scrapers:
            logger.info(f"Scraping: {s.name}")
            tenders = await _run_with_retries(s, self.cfg)

            total_found += len(tenders)
            for t in tenders:
                hay = f"{t.title}\n{t.description}".lower()
                kw_hit = any(k in hay for k in self.cfg.keywords)

                if not self.relevance.is_relevant(t):
                    if not kw_hit: skipped_kw += 1
                    else:          skipped_sim += 1
                    continue

                row = t.to_row()  # (embedding added later only if inserted)
                h = row_hash(row)
                row["tender_hash"] = h

                inserted = self.db.upsert_tender(row)
                if inserted:
                    emb = self.embedder.embed(f"{t.title} {t.description}")
                    self.db.update_embedding(row, emb)
                    total_new += 1
                    self._notify_new(t)
                    self.crm.push(row)
                else:
                    skipped_dupe += 1

        logger.info(
            f"Run complete. Found: {total_found} | New: {total_new} | "
            f"Skipped(dupe): {skipped_dupe} | Skipped(relevance_kw): {skipped_kw} | Skipped(relevance_sim): {skipped_sim}"
        )

    def _notify_new(self, t):
        msg = (
            f"New Tender: {t.title}\n"
            f"Buyer: {t.buyer or '-'}\n"
            f"Closes: {t.closing_date or '-'}\n"
            f"Link: {t.link}\n"
            f"Source: {t.source_portal}"
        )
        self.notifier.slack(msg)
        self.notifier.email(subject=f"New Tender: {t.title}", body=msg)

async def _loop(bot: TenderBot, seconds: int):
    if seconds <= 0:
        await bot.run_once()
        return
    while True:
        await bot.run_once()
        await asyncio.sleep(seconds)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--loop", type=int, default=0)
    args = parser.parse_args()

    cfg = Config.load()
    bot = TenderBot(cfg)
    if args.init_db:
        bot.db.init()
    asyncio.run(_loop(bot, args.loop))
