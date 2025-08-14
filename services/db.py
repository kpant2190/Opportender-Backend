from supabase import create_client, Client
from utils.logger import logger
from utils.helpers import row_hash
from utils.config import Config
from typing import Dict, Any

CREATE_TENDERS_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
create table if not exists tenders (
    id uuid primary key default gen_random_uuid(),
    tender_hash text unique,
    title text,
    description text,
    category text,
    closing_date date,
    buyer text,
    link text,
    contact_name text,
    contact_email text,
    tender_value numeric,
    source_portal text,
    embedding jsonb,
    created_at timestamptz default now()
);
"""

class DB:
    def __init__(self, cfg: Config):
        if not cfg.supabase_url or not cfg.supabase_key:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        self.client: Client = create_client(cfg.supabase_url, cfg.supabase_key)

    def init(self):
        try:
            self.client.table("tenders").select("id").limit(1).execute()
            logger.info("Table 'tenders' exists (or you have access). If not, create it via SQL editor with the DDL in README.md")
        except Exception as e:
            logger.warning("If table doesn't exist, create it with the SQL DDL. Error: %s", e)


    def upsert_tender(self, row: Dict[str, Any]) -> bool:
        h = row_hash(row)
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

    def update_embedding(self, row: Dict[str, Any], embedding) -> None:
        """Set embedding for the row identified by its hash."""
        try:
            h = row.get("tender_hash") or row_hash(row)
            self.client.table("tenders").update({"embedding": embedding}).eq("tender_hash", h).execute()
        except Exception as e:
            logger.error("DB update_embedding failed: %s", e)
