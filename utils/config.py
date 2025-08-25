from __future__ import annotations
# tenderbot/utils/config.py
import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv

# Load .env from repo root/parents exactly once, before anything else reads env
load_dotenv(find_dotenv(usecwd=True))

# --- helpers ---------------------------------------------------------------

def _clean_secret(val: Optional[str]) -> str:
    """Trim whitespace and remove wrapping single/double quotes."""
    if not val:
        return ""
    s = val.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s

def _is_placeholder(val: str) -> bool:
    """Detect placeholder-y values that should be treated as 'unset'."""
    v = val.strip().lower()
    return (
        not v
        or v.startswith("<your-")          # e.g. <your-openai-api-key>
        or v in {"xxx", "changeme", "todo"}
    )

def _validate_openai_key(val: str) -> None:
    """Fail fast with a clear message if the key is absent or placeholder."""
    if _is_placeholder(val):
        raise RuntimeError(
            "OPENAI_API_KEY is missing or a placeholder. "
            "Set a real key in your environment or .env (no quotes)."
        )
    # Optional: basic shape checks (OpenAI keys typically start with 'sk-')
    # Allow non 'sk-' keys in case of gateways/Azure:
    if not (val.startswith("sk-") or len(val) >= 20):
        # Don't block, but warn in your logger if you have one
        pass

# --- your Config -----------------------------------------------------------

@dataclass
class Config:
    # --- Supabase ---
    supabase_url: str = ""
    supabase_key: str = ""

    # --- OpenAI / Embeddings ---
    openai_api_key: str = ""
    openai_api_base: Optional[str] = None          # e.g. custom gateway / Azure AOAI base URL
    openai_org: Optional[str] = None               # optional org id
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 128
    embedding_timeout: float = 15.0

    # --- Notifications ---
    slack_webhook_url: Optional[str] = None
    email_host: Optional[str] = None
    email_port: int = 587
    email_user: Optional[str] = None
    email_pass: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None

    # --- CRM ---
    hubspot_api_key: Optional[str] = None
    hubspot_pipeline_id: Optional[str] = None
    hubspot_dealstage_id: Optional[str] = None
    crm_webhook_url: Optional[str] = None

    # --- Relevance / Filtering ---
    similarity_threshold: float = 0.78
    keywords: List[str] = None

    # --- Scraper runtime ---
    items_per_page: int = 200
    max_items_per_portal: int = 250
    scraper_timeout_seconds: int = 15
    retry_attempts: int = 1
    retry_backoff_base: int = 2
    retry_jitter_ms: int = 200
    
    # --- Per-scraper timeouts ---
    timeout_austender: int = 0
    timeout_qtenders: int = 0
    timeout_tendersvic: int = 0
    timeout_static_example: int = 0

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = [
                "it services", "computer systems", "software development", "network infrastructure",
                "cloud migration", "cybersecurity", "managed services", "data analytics",
                "it consulting", "erp implementation",
            ]

    @classmethod
    def load(cls) -> "Config":
        # Keywords
        kws_env = os.getenv("KEYWORDS", "").strip()
        keywords = [k.strip().lower() for k in kws_env.split(",") if k.strip()] or [
            "it services", "computer systems", "software development", "network infrastructure",
            "cloud migration", "cybersecurity", "managed services", "data analytics",
            "it consulting", "erp implementation",
        ]

        # Scraper controls
        scraper_timeout_seconds = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))
        retry_attempts = int(os.getenv("RETRY_ATTEMPTS", "1"))
        retry_backoff_base = int(os.getenv("RETRY_BACKOFF_BASE", "2"))
        retry_jitter_ms = int(os.getenv("RETRY_JITTER_MS", "200"))
        
        # Per-scraper timeouts (0 = use default)
        timeout_austender = int(os.getenv("TIMEOUT_AUSTENDER", "0"))
        timeout_qtenders = int(os.getenv("TIMEOUT_QTENDERS", "0"))
        timeout_tendersvic = int(os.getenv("TIMEOUT_TENDERSVIC", "0"))
        timeout_static_example = int(os.getenv("TIMEOUT_STATIC_EXAMPLE", "0"))

        # Embedding controls
        embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        # Default dims for common models
        default_dims = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        embedding_dim = int(os.getenv("EMBEDDING_DIM", str(default_dims.get(embedding_model, 1536))))
        embedding_batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "128"))
        embedding_timeout = float(os.getenv("EMBEDDING_TIMEOUT", "15"))

        # Clean & normalize OpenAI config
        openai_api_key = _clean_secret(os.getenv("OPENAI_API_KEY", ""))
        openai_api_base = _clean_secret(os.getenv("OPENAI_API_BASE", ""))
        openai_org = _clean_secret(os.getenv("OPENAI_ORG", "")) or None

        # Treat placeholders/empties correctly
        if _is_placeholder(openai_api_base):
            openai_api_base = None

        # Validate the API key up front (clearer than letting HTTP 401 bubble later)
        _validate_openai_key(openai_api_key)

        # read from environment (populated by .env above)
        cfg = cls(
            # Supabase
            supabase_url=(os.getenv("SUPABASE_URL") or "").strip(),
            supabase_key=(os.getenv("SUPABASE_KEY") or "").strip(),

            # OpenAI / Embeddings
            openai_api_key=openai_api_key,
            openai_api_base=openai_api_base,
            openai_org=openai_org,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            embedding_batch_size=embedding_batch_size,
            embedding_timeout=embedding_timeout,

            # Notifications
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
            email_host=os.getenv("EMAIL_HOST"),
            email_port=int(os.getenv("EMAIL_PORT", "587")),
            email_user=os.getenv("EMAIL_USER"),
            email_pass=os.getenv("EMAIL_PASS"),
            email_from=os.getenv("EMAIL_FROM"),
            email_to=os.getenv("EMAIL_TO"),

            # CRM
            hubspot_api_key=os.getenv("HUBSPOT_API_KEY"),
            hubspot_pipeline_id=os.getenv("HUBSPOT_PIPELINE_ID"),
            hubspot_dealstage_id=os.getenv("HUBSPOT_DEALSTAGE_ID"),
            crm_webhook_url=os.getenv("CRM_WEBHOOK_URL"),

            # Relevance
            similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.78")),
            keywords=keywords,

            # Scraper runtime
            items_per_page=int(os.getenv("ITEMS_PER_PAGE", "200")),
            max_items_per_portal=int(os.getenv("MAX_ITEMS_PER_PORTAL", "250")),
            scraper_timeout_seconds=scraper_timeout_seconds,
            retry_attempts=retry_attempts,
            retry_backoff_base=retry_backoff_base,
            retry_jitter_ms=retry_jitter_ms,
            
            # Per-scraper timeouts
            timeout_austender=timeout_austender,
            timeout_qtenders=timeout_qtenders,
            timeout_tendersvic=timeout_tendersvic,
            timeout_static_example=timeout_static_example,
        )

        # Optional: quick sanity log (redacted)
        try:
            from tenderbot.utils.logger import logger
            logger.info(
                "Config loaded: SUPABASE_URL=%s SUPABASE_KEY=%s OPENAI_API_KEY=%s",
                ("<set>" if cfg.supabase_url else "<missing>"),
                ("<set>" if cfg.supabase_key else "<missing>"),
                ("<set>" if cfg.openai_api_key else "<missing>"),
            )
        except Exception:
            pass

        return cfg

