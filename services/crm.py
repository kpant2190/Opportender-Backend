from utils.logger import logger
from utils.config import Config

class CRM:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def push(self, tender_row: dict):
        if not self.cfg.hubspot_api_key:
            logger.debug("No HUBSPOT_API_KEY; skipping CRM push")
            return
        logger.info(f"[CRM] Would push tender: {tender_row.get('title')}")
