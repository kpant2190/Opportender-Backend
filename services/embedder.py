from __future__ import annotations
# tenderbot/services/embedder.py
from typing import List, Dict, Any, Optional
import os
import time
import math
import hashlib

# Package-qualified imports for module mode
from tenderbot.utils.config import Config
from tenderbot.utils.logger import logger

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


_MODEL_DIMS = {
    # Known OpenAI embedding models
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,  # legacy
}


class Embedder:
    """
    Thin embedding client with:
      - OpenAI support (if OPENAI_API_KEY present)
      - Deterministic fallback (no network)
      - Cache
      - Batch embedding
    Returns a Python list[float] of length `embedding_dim`.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

        # Build client from validated config
        self.client = None
        if OpenAI and cfg.openai_api_key:
            try:
                kwargs: Dict[str, Any] = {"api_key": cfg.openai_api_key}
                if cfg.openai_api_base:
                    kwargs["base_url"] = cfg.openai_api_base
                if cfg.openai_org:
                    kwargs["organization"] = cfg.openai_org
                self.client = OpenAI(**kwargs)
                logger.info(f"Embedder: using OpenAI model '{cfg.embedding_model}' (dim={cfg.embedding_dim})")
            except Exception as e:
                logger.error(f"Embedder: OpenAI client init failed: {e}. Falling back to local embedding.")
                self.client = None
        else:
            logger.info(f"Embedder: no API key; using deterministic local embeddings (dim={cfg.embedding_dim}).")

        self.model = cfg.embedding_model
        self.embedding_dim = cfg.embedding_dim
        self.batch_size = cfg.embedding_batch_size
        self.request_timeout = cfg.embedding_timeout

        self.cache: Dict[str, List[float]] = {}

    # -------------------- Public API --------------------

    def embed(self, text: str) -> List[float]:
        """
        Embed a single text. Returns a dense vector of length `self.embedding_dim`.
        """
        text = (text or "").strip()
        if not text:
            return [0.0] * self.embedding_dim

        if text in self.cache:
            return self.cache[text]

        vec: List[float]
        if not self.client:
            vec = self._fallback_vector(text, self.embedding_dim)
        else:
            try:
                resp = self.client.embeddings.create(
                    model=self.model,
                    input=text,
                    timeout=self.request_timeout,
                )
                vec = list(resp.data[0].embedding)  # type: ignore
            except Exception as e:
                # Do NOT log the key; keep the message safe but useful
                logger.error(f"Embedding failed: {e}")
                vec = self._fallback_vector(text, self.embedding_dim)

        vec = self._ensure_dim(vec, self.embedding_dim)
        self.cache[text] = vec
        return vec

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """
        Batch embed. Preserves order; returns list of vectors (possibly empty lists for blank inputs).
        """
        if not texts:
            return []

        # Use cache first, collect indices to compute
        results: List[Optional[List[float]]] = [None] * len(texts)
        to_query: List[str] = []
        map_idx: List[int] = []

        for i, t in enumerate(texts):
            s = (t or "").strip()
            if not s:
                results[i] = [0.0] * self.embedding_dim
                continue
            if s in self.cache:
                results[i] = self.cache[s]
            else:
                to_query.append(s)
                map_idx.append(i)

        # If nothing new, return from cache
        if not to_query:
            return [r if r is not None else [0.0] * self.embedding_dim for r in results]

        if not self.client:
            # Local deterministic fallback
            for s, i in zip(to_query, map_idx):
                vec = self._fallback_vector(s, self.embedding_dim)
                vec = self._ensure_dim(vec, self.embedding_dim)
                self.cache[s] = vec
                results[i] = vec
            return [r if r is not None else [0.0] * self.embedding_dim for r in results]

        # OpenAI batch in chunks
        chunk = max(1, self.batch_size)
        cursor = 0
        while cursor < len(to_query):
            batch = to_query[cursor : cursor + chunk]
            # simple retry loop
            for attempt in range(3):
                try:
                    resp = self.client.embeddings.create(
                        model=self.model,
                        input=batch,
                        timeout=self.request_timeout,
                    )
                    embs = [list(d.embedding) for d in resp.data]  # type: ignore
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"Batch embedding failed after retries: {e}. Falling back for this chunk.")
                        embs = [self._fallback_vector(s, self.embedding_dim) for s in batch]
                        break
                    sleep_for = 1.5 * (2 ** attempt)
                    logger.warning(f"Batch embedding error: {e}. Retrying in {sleep_for:.1f}s...")
                    time.sleep(sleep_for)

            # place in results
            for s, i, vec in zip(batch, map_idx[cursor : cursor + chunk], embs):
                v = self._ensure_dim(vec, self.embedding_dim)
                self.cache[s] = v
                results[i] = v

            cursor += chunk

        return [r if r is not None else [0.0] * self.embedding_dim for r in results]

    # -------------------- Internals --------------------

    @staticmethod
    def _ensure_dim(vec: List[float], dim: int) -> List[float]:
        """
        Ensure exact dimension: truncate or pad with zeros.
        """
        if not isinstance(vec, list):
            try:
                vec = list(vec)  # type: ignore
            except Exception:
                vec = []
        if len(vec) == dim:
            return vec
        if len(vec) > dim:
            return vec[:dim]
        # pad
        return vec + [0.0] * (dim - len(vec))

    @staticmethod
    def _fallback_vector(text: str, dim: int) -> List[float]:
        """
        Deterministic, dimension-stable embedding without network:
        For each index i, hash(text + '#' + i) with SHA256, take first 4 bytes as uint32,
        scale to [0,1). This yields a repeatable pseudo-embedding of length `dim`.
        """
        out = [0.0] * dim
        for i in range(dim):
            h = hashlib.sha256(f"{text}#{i}".encode("utf-8")).digest()
            # first 4 bytes to uint32, then normalize to [0,1)
            val = int.from_bytes(h[:4], "big") / 2**32
            out[i] = float(val)
        return out

