from __future__ import annotations
# tenderbot/utils/helpers.py
import hashlib
import math
import re
from typing import Dict, Any, List, Optional, Iterable
from datetime import datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


# --------------------------- Text / URL utils ---------------------------

_WS_RE = re.compile(r"\s+")
def normalize_ws(s: Optional[str]) -> str:
    """Collapse whitespace and trim."""
    return _WS_RE.sub(" ", (s or "").strip())

def canonicalize_url(u: Optional[str]) -> str:
    """
    Normalize URLs for hashing/dedup:
    - lower-case scheme/host
    - remove fragment
    - keep query but sort keys
    """
    if not u:
        return ""
    try:
        p = urlparse(u)
        # sort query parameters deterministically
        q = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
        return urlunparse((
            (p.scheme or "").lower(),
            (p.netloc or "").lower(),
            p.path or "",
            p.params or "",
            q,
            ""  # strip fragment
        ))
    except Exception:
        return (u or "").strip()


# --------------------------- Hashing / dedup ----------------------------

def row_hash(row: Dict[str, Any]) -> str:
    """
    Stable SHA256 over key identity fields.
    We include source_portal + source_id + title + buyer + link (canonicalized),
    which is stronger than date-based keys and robust to minor text changes.
    """
    pieces = [
        normalize_ws(row.get("source_portal")),
        normalize_ws(row.get("source_id")),       # may be None; normalize_ws -> ""
        normalize_ws(row.get("title")),
        normalize_ws(row.get("buyer")),
        canonicalize_url(row.get("link")),
    ]
    key = "|".join(pieces).encode("utf-8")
    return hashlib.sha256(key).hexdigest()


# --------------------------- Similarity ---------------------------------

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# --------------------------- Date parsing -------------------------------

# Accept a wide spread of AU tender formats
_DATE_FORMATS = (
    "%d-%b-%Y",
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y %I:%M%p",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M%p",
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %b, %Y",
    "%d %B %Y",
)

_DATETIME_FORMATS = (
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y %I:%M%p",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M%p",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
)

def parse_date_safe(s: Optional[str]) -> Optional[str]:
    """
    Parse many common date formats → 'YYYY-MM-DD' (date only).
    Returns None if parsing fails.
    """
    if not s:
        return None
    txt = normalize_ws(s)
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(txt, fmt).date()
            return d.isoformat()
        except Exception:
            continue
    # try ISO-like recovery
    try:
        return datetime.fromisoformat(txt).date().isoformat()
    except Exception:
        return None

def parse_datetime_safe(s: Optional[str]) -> Optional[str]:
    """
    Parse many common date/time formats → ISO 8601 timestamp (naive).
    Useful for closing_ts. Returns None if parsing fails.
    """
    if not s:
        return None
    txt = normalize_ws(s)
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(txt, fmt)
            return dt.isoformat()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(txt).isoformat()
    except Exception:
        return None


# --------------------------- Numbers / Money ----------------------------

_MONEY_RE = re.compile(r"[^\d\.\-]")

def money_to_float(s: Optional[str]) -> Optional[float]:
    """
    Convert currency strings like '$1,234.56' or 'AUD 12,000' → 1234.56.
    Returns None if empty or unparsable.
    """
    if not s:
        return None
    raw = _MONEY_RE.sub("", s)
    if not raw:
        return None
    try:
        return float(raw)
    except Exception:
        return None


# --------------------------- Misc helpers -------------------------------

def preview(text: Optional[str], n: int = 140) -> str:
    t = normalize_ws(text)
    return (t[:n] + "…") if len(t) > n else t

def join_nonempty(parts: Iterable[Optional[str]], sep: str = " ") -> str:
    return sep.join([normalize_ws(p) for p in parts if normalize_ws(p)])

