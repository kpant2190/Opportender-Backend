from __future__ import annotations
# tenderbot/services/crm.py
from typing import Any, Dict, Optional
import json
import time
import requests

from tenderbot.utils.logger import logger
from tenderbot.utils.config import Config


class CRM:
    """
    Minimal CRM integration.
    - If HUBSPOT_API_KEY is set, creates a Deal (dealname + optional amount/pipeline/dealstage/closedate).
    - Else if CRM_WEBHOOK_URL is set, POSTs the tender row JSON to that webhook (your server can fan out).
    - Else: logs and returns.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "TenderBot/CRM"})

        # Read config (these should be in Config via env)
        self.hubspot_api_key: Optional[str] = getattr(cfg, "hubspot_api_key", None)
        self.hubspot_pipeline_id: Optional[str] = getattr(cfg, "hubspot_pipeline_id", None)
        self.hubspot_dealstage_id: Optional[str] = getattr(cfg, "hubspot_dealstage_id", None)
        self.crm_webhook_url: Optional[str] = getattr(cfg, "crm_webhook_url", None)

        if self.hubspot_api_key:
            logger.info("CRM: HubSpot configured")
        elif self.crm_webhook_url:
            logger.info("CRM: Webhook configured")
        else:
            logger.debug("CRM: No destination configured; will just log pushes")

    # ----- Public API -------------------------------------------------------

    def push(self, tender_row: Dict[str, Any]) -> None:
        """
        Push a single tender to CRM. Safe no-op if not configured.
        Call this only for NEW rows (your runner already filters inserted items).
        """
        # Prefer HubSpot if configured; else webhook; else log.
        if self.hubspot_api_key:
            try:
                self._push_hubspot_deal(tender_row)
                return
            except Exception as e:
                logger.error(f"[CRM] HubSpot push failed: {e}. Falling back to webhook/log.")

        if self.crm_webhook_url:
            try:
                self._post_webhook(tender_row)
                return
            except Exception as e:
                logger.error(f"[CRM] Webhook push failed: {e}. Will log only.")

        # Last resort: log
        logger.info(f"[CRM] (dry-run) {tender_row.get('title')} | {tender_row.get('link')}")

    # ----- Implementations --------------------------------------------------

    def _push_hubspot_deal(self, row: Dict[str, Any]) -> None:
        """
        Create a Deal in HubSpot CRM.
        Required: HUBSPOT_API_KEY
        Optional: HUBSPOT_PIPELINE_ID, HUBSPOT_DEALSTAGE_ID
        Docs: https://developers.hubspot.com/docs/api/crm/deals
        """
        api_base = "https://api.hubapi.com"
        url = f"{api_base}/crm/v3/objects/deals"

        # Required property: dealname
        dealname = row.get("title") or (row.get("buyer") and f"{row['buyer']} tender") or "Tender"
        props: Dict[str, Any] = {
            "dealname": str(dealname)[:255],
        }

        # Optional amount
        amount = row.get("tender_value")
        if isinstance(amount, (int, float)):
            props["amount"] = float(amount)

        # Optional close date (HubSpot expects ms epoch)
        # Use closing_ts if available; otherwise closing_date at midnight local
        closed_iso = row.get("closing_ts") or row.get("closing_date")
        if isinstance(closed_iso, str) and closed_iso:
            try:
                # Very forgiving parse: just take first 19 chars if ISO with time
                # and convert to epoch ms. If only YYYY-MM-DD, assume 17:00 UTC.
                ts_sec = self._to_epoch_seconds(closed_iso)
                props["closedate"] = int(ts_sec * 1000)
            except Exception:
                pass

        # Optional pipeline/stage
        if self.hubspot_pipeline_id:
            props["pipeline"] = self.hubspot_pipeline_id
        if self.hubspot_dealstage_id:
            props["dealstage"] = self.hubspot_dealstage_id

        # ⚠️ HubSpot rejects unknown property names; keep to core fields above.
        payload = {"properties": props}

        headers = {
            "Authorization": f"Bearer {self.hubspot_api_key}",
            "Content-Type": "application/json",
        }
        resp = self._session.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if resp.status_code >= 300:
            raise RuntimeError(f"HubSpot error {resp.status_code}: {resp.text}")

        deal_id = (resp.json() or {}).get("id")
        logger.info(f"[CRM] HubSpot deal created: {deal_id} | {props.get('dealname')}")

    def _post_webhook(self, row: Dict[str, Any]) -> None:
        """
        POST the row JSON to an arbitrary webhook owned by you.
        """
        headers = {"Content-Type": "application/json"}
        resp = self._session.post(self.crm_webhook_url, data=json.dumps(row), headers=headers, timeout=20)
        if resp.status_code >= 300:
            raise RuntimeError(f"Webhook error {resp.status_code}: {resp.text}")
        logger.info("[CRM] Webhook delivered")

    # ----- Utils ------------------------------------------------------------

    @staticmethod
    def _to_epoch_seconds(dt_like: str) -> float:
        """
        Very lightweight parser for ISO date/time strings:
        - 'YYYY-MM-DDTHH:MM:SSZ'  -> parsed as UTC
        - 'YYYY-MM-DD'            -> 17:00 UTC that day
        """
        s = dt_like.strip()
        # If time-like present, trim to seconds and parse as UTC
        if "T" in s:
            # Cut to YYYY-MM-DDTHH:MM:SS if longer
            core = s[:19]
            # naive parse to struct
            import time as _time
            t = _time.strptime(core, "%Y-%m-%dT%H:%M:%S")
            return time.mktime(t)  # local epoch; acceptable for rough close date
        else:
            # Date-only: 17:00 UTC
            core = s[:10]
            import datetime as _dt
            d = _dt.datetime.strptime(core, "%Y-%m-%d")
            d = d.replace(hour=17, minute=0, second=0)
            # treat as UTC—convert to epoch seconds
            return d.replace(tzinfo=_dt.timezone.utc).timestamp()

