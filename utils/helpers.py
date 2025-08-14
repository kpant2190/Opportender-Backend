import hashlib
import math
from typing import Dict, Any, List, Optional
from datetime import datetime

def row_hash(row: Dict[str, Any]) -> str:
    m = hashlib.sha256()
    key = f"{row.get('title','')}|{row.get('buyer','')}|{row.get('closing_date','')}|{row.get('link','')}".encode()
    m.update(key)
    return m.hexdigest()

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

def parse_date_safe(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return str(d)
        except Exception:
            continue
    return None
