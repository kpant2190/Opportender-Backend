import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

@dataclass
class Config:
    supabase_url: str
    supabase_key: str
    openai_api_key: Optional[str]
    slack_webhook_url: Optional[str]
    email_host: Optional[str]
    email_port: int
    email_user: Optional[str]
    email_pass: Optional[str]
    email_from: Optional[str]
    email_to: Optional[str]
    hubspot_api_key: Optional[str]
    similarity_threshold: float
    keywords: List[str]
    items_per_page: int
    max_items_per_portal: int
    scraper_timeout_seconds: int
    retry_attempts: int
    retry_backoff_base: int
    retry_jitter_ms: int

    @staticmethod
    def load() -> "Config":
        load_dotenv()
        kws = os.getenv("KEYWORDS", "").strip()
        keywords = [k.strip().lower() for k in kws.split(",") if k.strip()] or [
            "it services","computer systems","software development","network infrastructure",
            "cloud migration","cybersecurity","managed services","data analytics",
            "it consulting","erp implementation",
        ]
        scraper_timeout_seconds = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "12"))
        retry_attempts = int(os.getenv("RETRY_ATTEMPTS", "2"))
        retry_backoff_base = int(os.getenv("RETRY_BACKOFF_BASE", "2"))
        retry_jitter_ms = int(os.getenv("RETRY_JITTER_MS", "300"))
        return Config(
            supabase_url=os.getenv("SUPABASE_URL", ""),
            supabase_key=os.getenv("SUPABASE_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
            email_host=os.getenv("EMAIL_HOST"),
            email_port=int(os.getenv("EMAIL_PORT", "587")),
            email_user=os.getenv("EMAIL_USER"),
            email_pass=os.getenv("EMAIL_PASS"),
            email_from=os.getenv("EMAIL_FROM"),
            email_to=os.getenv("EMAIL_TO"),
            hubspot_api_key=os.getenv("HUBSPOT_API_KEY"),
            similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.75")),
            keywords=keywords,
            items_per_page=int(os.getenv("ITEMS_PER_PAGE", "100")),
            max_items_per_portal=int(os.getenv("MAX_ITEMS_PER_PORTAL", "400")),
            scraper_timeout_seconds=scraper_timeout_seconds,
            retry_attempts=retry_attempts,
            retry_backoff_base=retry_backoff_base,
            retry_jitter_ms=retry_jitter_ms,
        )
