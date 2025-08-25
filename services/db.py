from __future__ import annotations
import json
from datetime import date
ALLOWED_COLS = {
    "source_portal","title","description","link","source_id","atm_id","category",
    "buyer","location","publish_date","closing_date","closing_ts","tender_value",
    "contact_name","contact_email","tender_hash","embedding"
}

def _coerce_date_yyyy_mm_dd(v):
    if v in (None, "", "N/A"):
        return None
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return v[:10]  # assume ISO-ish string; keeps 'YYYY-MM-DD'
    return None

def _normalize_row(r):
    # Tender dataclass -> dict
    if hasattr(r, "to_row"):
        r = r.to_row()
    # JSON string -> dict
    if isinstance(r, str):
        try:
            r = json.loads(r)
        except Exception:
            logger.error("Skipping row: string could not be parsed as JSON: %s", r[:120])
            return None
    if not isinstance(r, dict):
        logger.error("Skipping row: expected dict, got %r", type(r))
        return None

    # type coercions
    r["publish_date"] = _coerce_date_yyyy_mm_dd(r.get("publish_date"))
    r["closing_date"] = _coerce_date_yyyy_mm_dd(r.get("closing_date"))
    tv = r.get("tender_value")
    r["tender_value"] = float(tv) if isinstance(tv, (int, float)) else None

    # keep only allowed columns
    return {k: r.get(k) for k in ALLOWED_COLS}
# tenderbot/services/db.py
from typing import Dict, Any, List, Iterable, Set
from datetime import datetime, timezone
import os

from supabase import create_client, Client
from tenderbot.utils.logger import logger
from tenderbot.utils.helpers import row_hash
from tenderbot.utils.config import Config


class DB:
    def __init__(self, cfg: Config | None = None):
        if cfg is None:
            cfg = Config.load()

        # prefer config, then env (in case you *also* export in shell)
        self.url = (cfg.supabase_url or os.getenv("SUPABASE_URL") or "").strip()
        self.key = (cfg.supabase_key or os.getenv("SUPABASE_KEY") or "").strip()

        if not self.url or not self.key:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")

        self.client: Client = create_client(self.url, self.key)

    # ------------------------ bootstrap / sanity ------------------------

    def init(self):
        """Light sanity check that the table exists and is reachable."""
        try:
            self.client.table("tenders").select("id").limit(1).execute()
            logger.info("DB init: 'tenders' table reachable.")
        except Exception as e:
            logger.warning("DB init: couldn't query 'tenders'. Create schema first. Error: %s", e)

    # ------------------------ single-row legacy -------------------------

    def upsert_tender(self, row: Dict[str, Any]) -> bool:
        """
        Legacy single-row path. Returns True if inserted, False if already existed.
        Prefer using upsert_tenders_return_inserted for batches.
        """
        h = row.get("tender_hash") or row_hash(row)
        row["tender_hash"] = h
        try:
            existing = self.client.table("tenders").select("id").eq("tender_hash", h).execute()
            if existing.data:
                return False
            self.client.table("tenders").insert(row).execute()
            return True
        except Exception as e:
            logger.error("DB upsert failed: %s", e)
            return False

    def update_embedding(self, row: Dict[str, Any], embedding: Any) -> None:
        """
        Set JSON embedding for the row identified by its hash.
        (Optionally extend to also set embedding_vec if your embedder returns a raw float list.)
        """
        try:
            h = row.get("tender_hash") or row_hash(row)
            payload: Dict[str, Any] = {"embedding": embedding}
            # If you also want to write vector(1536):
            # if isinstance(embedding, dict) and "data" in embedding:
            #     vec = embedding["data"][0]["embedding"]
            #     payload["embedding_vec"] = vec
            self.client.table("tenders").update(payload).eq("tender_hash", h).execute()
        except Exception as e:
            logger.error("DB update_embedding failed: %s", e)

    # ------------------------ batch paths (preferred) -------------------

    def upsert_tenders_return_inserted(self, rows: List[dict]) -> list:
        # Normalise & filter
        norm = []
        for r in rows:
            nr = _normalize_row(r)
            if nr:
                norm.append(nr)

        if not norm:
            logger.info("Nothing to upsert after normalisation.")
            return []

        # Try RPC
        try:
            res = self.client.rpc("upsert_tenders_batch", {"payload": norm}).execute()
            return (res.data or [])
        except Exception as e:
            logger.error("RPC upsert_tenders_batch failed, falling back: %s", e)

        # Fallback: table upsert on unique (source_portal,source_id)
        res = (
            self.client.table("tenders")
            .upsert(norm, on_conflict="source_portal,source_id", returning="representation")
            .execute()
        )
        return (res.data or [])

    def _get_existing_hashes(self, hashes: Iterable[str]) -> Set[str]:
        if not hashes:
            return set()
        try:
            res = (
                self.client.table("tenders")
                .select("tender_hash")
                .in_("tender_hash", list(hashes))
                .execute()
            )
            return {x["tender_hash"] for x in (res.data or []) if x.get("tender_hash")}
        except Exception as e:
            logger.error("Preflight select failed: %s", e)
            return set()

    # ------------------------ notification marker ----------------------

    def set_notified_at(self, tender_hash: str) -> None:
        """Mark a tender as notified now."""
        try:
            self.client.table("tenders") \
                .update({"notified_at": "now()"}) \
                .eq("tender_hash", tender_hash) \
                .execute()
        except Exception as e:
            logger.error("DB set_notified_at failed: %s", e)

    def mark_notified(self, hashes: Iterable[str]) -> None:
        """
        Set notified_at = now() for all given tender_hash values.
        Safe no-op if list is empty.
        """
        hs = list({h for h in hashes if h})
        if not hs:
            return
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.client.table("tenders").update({"notified_at": now_iso}).in_("tender_hash", hs).execute()
        except Exception as e:
            logger.error("mark_notified failed: %s", e)

