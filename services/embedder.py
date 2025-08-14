from typing import List, Dict, Optional
from utils.config import Config
from utils.logger import logger

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

class Embedder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.openai_api_key) if (OpenAI and cfg.openai_api_key) else None
        self.cache: Dict[str, List[float]] = {}

    def embed(self, text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return []
        if text in self.cache:
            return self.cache[text]
        if not self.client:
            vec = [((i + sum(ord(c) for c in text)) % 97) / 97.0 for i in range(256)]
            self.cache[text] = vec
            return vec
        try:
            resp = self.client.embeddings.create(model="text-embedding-3-small", input=text)
            vec = resp.data[0].embedding  # type: ignore
            self.cache[text] = vec
            return vec
        except Exception as e:
            logger.error("Embedding failed, using fallback: %s", e)
            vec = [((i + sum(ord(c) for c in text)) % 97) / 97.0 for i in range(256)]
            self.cache[text] = vec
            return vec
