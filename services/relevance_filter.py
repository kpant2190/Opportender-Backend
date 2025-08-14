from services.embedder import Embedder
from utils.config import Config
from utils.helpers import cosine_similarity

class RelevanceFilter:
    def __init__(self, cfg: Config, embedder: Embedder):
        self.cfg = cfg
        self.embedder = embedder
        self.query_vec = self.embedder.embed(
            " ".join(cfg.keywords) + " computer system design services IT consulting RFP tender"
        )

    def is_relevant(self, t) -> bool:
        hay = f"{t.title}\n{t.description}".lower()
        if any(k in hay for k in self.cfg.keywords):
            return True
        vec = self.embedder.embed(f"{t.title} {t.description}")
        sim = cosine_similarity(self.query_vec, vec)
        return sim >= self.cfg.similarity_threshold
