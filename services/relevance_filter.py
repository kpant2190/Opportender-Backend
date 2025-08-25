from __future__ import annotations
# tenderbot/services/relevance_filter.py
from typing import Any, Dict, Iterable, Tuple

from tenderbot.services.embedder import Embedder
from tenderbot.utils.config import Config
from tenderbot.utils.helpers import cosine_similarity


class RelevanceFilter:
    """
    Two-stage relevance:
      1) Keyword substring hit -> relevant
      2) Else semantic sim(query_vec, tender_vec) >= threshold
    """

    def __init__(self, cfg: Config, embedder: Embedder):
        self.cfg = cfg
        self.embedder = embedder

        # Normalize keywords once
        kws = [k.strip().lower() for k in (cfg.keywords or []) if k and k.strip()]
        self._keywords = kws

        # Build query text for embeddings
        if kws:
            query_text = " ".join(kws)
        else:
            # Fallback generic relevance intent (broad, tech + services tender phrasing)
            query_text = (
                "request for tender rft rfp rfi rfq government procurement "
                "it services software cloud cyber data analytics consulting integration managed services"
            )

        self.query_vec = self.embedder.embed(query_text)
        # Default threshold if not provided
        self.threshold = float(getattr(cfg, "similarity_threshold", 0.75))

    # ------------- Public API -------------

    def is_relevant(self, t: Any) -> bool:
        title, desc = _title_desc(t)
        hay = f"{(title or '')}\n{(desc or '')}".lower()

        # 1) Cheap keyword pass
        if self._keywords and any(k in hay for k in self._keywords):
            return True

        # 2) Semantic similarity
        vec = self.embedder.embed(f"{title or ''} {desc or ''}".strip())
        sim = cosine_similarity(self.query_vec, vec)
        return sim >= self.threshold

    def explain(self, t: Any) -> Dict[str, Any]:
        """
        Optional helper for debugging/logging decisions.
        """
        title, desc = _title_desc(t)
        hay = f"{(title or '')}\n{(desc or '')}".lower()
        kw_hit = bool(self._keywords and any(k in hay for k in self._keywords))
        vec = self.embedder.embed(f"{title or ''} {desc or ''}".strip())
        sim = cosine_similarity(self.query_vec, vec)
        return {
            "kw_hit": kw_hit,
            "similarity": sim,
            "threshold": self.threshold,
            "decision": (kw_hit or sim >= self.threshold),
            "title_preview": (title or "")[:140],
        }


# ------------- helpers -------------

def _title_desc(t: Any) -> Tuple[str | None, str | None]:
    """
    Accept either Tender dataclass or dict-like record.
    """
    if isinstance(t, dict):
        return t.get("title"), t.get("description")
    # dataclass or object with attrs
    return getattr(t, "title", None), getattr(t, "description", None)

