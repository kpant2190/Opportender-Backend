from __future__ import annotations
# tenderbot/scripts/test_qtenders.py
import asyncio
import argparse
import json
from typing import Dict, Any

from tenderbot.utils.config import Config
from tenderbot.utils.logger import logger
from tenderbot.utils.helpers import row_hash
from tenderbot.services.embedder import Embedder
from tenderbot.services.relevance_filter import RelevanceFilter
from tenderbot.scrapers.qtenders_scraper import QTendersScraper


def to_db_row(t) -> Dict[str, Any]:
    """Normalize a Tender dataclass to the row we send to Supabase (no embedding here)."""
    row = t.to_row()  # already includes most fields
    # Make sure these always exist in the row dict:
    row.setdefault("source_portal", t.source_portal)
    row.setdefault("link", t.link)
    row.setdefault("source_id", getattr(t, "source_id", None))
    row.setdefault("atm_id", getattr(t, "atm_id", None))
    row.setdefault("location", getattr(t, "location", None))
    row.setdefault("publish_date", getattr(t, "publish_date", None))
    row.setdefault("closing_ts", getattr(t, "closing_ts", None))
    # Hash we use for dedupe:
    row["tender_hash"] = row_hash(row)
    # We keep 'embedding' None in test unless explicitly requested
    row.setdefault("embedding", None)
    return row


def pretty_print_row(i: int, row: Dict[str, Any], show_embedding_len: bool = True):
    """Console-friendly print of the row (without dumping huge text)."""
    desc = (row.get("description") or "").strip()
    if len(desc) > 400:
        desc_preview = desc[:400] + "…"
    else:
        desc_preview = desc

    payload = {
        "idx": i,
        "source_portal": row.get("source_portal"),
        "title": row.get("title"),
        "buyer": row.get("buyer"),
        "category": row.get("category"),
        "location": row.get("location"),
        "publish_date": row.get("publish_date"),
        "closing_date": row.get("closing_date"),
        "closing_ts": row.get("closing_ts"),
        "tender_value": row.get("tender_value"),
        "source_id": row.get("source_id"),
        "atm_id": row.get("atm_id"),
        "link": row.get("link"),
        "tender_hash": row.get("tender_hash"),
        "description": desc_preview,
    }
    if show_embedding_len:
        emb = row.get("embedding")
        payload["embedding_len"] = (len(emb) if isinstance(emb, list) else 0)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def main():
    parser = argparse.ArgumentParser(description="Test QTenders scraper and print rows that would be sent to Supabase.")
    parser.add_argument("--limit", type=int, default=50, help="Max items to fetch from listing.")
    parser.add_argument("--timeout", type=int, default=30, help="Overall scraper timeout (seconds).")
    parser.add_argument("--no-filter", action="store_true", help="Disable keyword/semantic filter.")
    parser.add_argument("--with-embedding", action="store_true", help="Compute embeddings and include them (length only printed).")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB (just print).")
    args = parser.parse_args()

    # Log the exact scraper module path being used
    import importlib
    mod = importlib.import_module("tenderbot.scrapers.qtenders_scraper")
    logger.info(f"[QTenders Test] using module: {mod.__file__}")

    cfg = Config.load()
    # apply limits to this run only
    cfg.max_items_per_portal = args.limit

    logger.info(f"[QTenders Test] start | limit={args.limit} | filter={'OFF' if args.no_filter else 'ON'} | dry_run={args.dry_run}")

    embedder = Embedder(cfg)
    relevance = RelevanceFilter(cfg, embedder)
    # Instantiate defensively in case an older class is imported:
    try:
        scraper = QTendersScraper(cfg)     # prefer passing cfg
    except TypeError:
        scraper = QTendersScraper()        # fallback if old signature is loaded

    # fetch with global timeout
    tenders = await asyncio.wait_for(scraper.fetch(), timeout=args.timeout)
    logger.info(f"Fetched {len(tenders)} tenders from QTenders.")

    # normalize + (optional) filter
    rows = []
    for t in tenders:
        if not args.no_filter and not relevance.is_relevant(t):
            continue
        row = to_db_row(t)
        rows.append(row)

    # (optional) embeddings
    if args.with_embedding and rows:
        for r in rows:
            text = f"{r.get('title','')} {r.get('description','')}".strip()
            r["embedding"] = embedder.embed(text)

    # print everything that would be sent
    print("\n===== ROWS THAT WOULD BE SENT TO SUPABASE =====")
    for i, r in enumerate(rows, 1):
        pretty_print_row(i, r, show_embedding_len=True)
    print(f"===== TOTAL: {len(rows)} rows =====\n")

    # optional write (kept here if you want the switch later)
    if not args.dry_run:
        # sanity check (redacted) so you immediately see what's loaded
        logger.info("SANITY: SUPABASE_URL=%s SUPABASE_KEY=%s",
                    "<set>" if cfg.supabase_url else "<missing>",
                    "<set>" if cfg.supabase_key else "<missing>")
        
        from tenderbot.services.db import DB
        db = DB(cfg)
        try:
            inserted = db.upsert_tenders_return_inserted(rows)
            logger.info(f"DB write complete. Inserted (new) rows: {len(inserted)}")
        except Exception as e:
            logger.error(f"DB write failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())

