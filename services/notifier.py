from __future__ import annotations
# tenderbot/services/notifier.py
from typing import Dict, Any, Iterable, Optional
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from tenderbot.utils.config import Config
from tenderbot.utils.logger import logger


MAX_SLACK_LEN = 2900  # keep some headroom under Slack's 3000 char block limit


class Notifier:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        # Slack webhook URL (optional)
        self._slack_url: Optional[str] = getattr(cfg, "slack_webhook_url", None)
        # Email settings (all must be present to enable email)
        self._email_host: Optional[str] = getattr(cfg, "email_host", None)
        self._email_port: Optional[int] = getattr(cfg, "email_port", None)
        self._email_user: Optional[str] = getattr(cfg, "email_user", None)
        self._email_pass: Optional[str] = getattr(cfg, "email_pass", None)
        self._email_from: Optional[str] = getattr(cfg, "email_from", None)
        self._email_to:   Optional[str] = getattr(cfg, "email_to", None)

        if self._slack_url:
            logger.info("Notifier: Slack enabled")
        if all([self._email_host, self._email_port, self._email_user, self._email_pass, self._email_from, self._email_to]):
            logger.info("Notifier: Email enabled")
        if not self._slack_url and not all([self._email_host, self._email_port, self._email_user, self._email_pass, self._email_from, self._email_to]):
            logger.debug("Notifier: no destinations configured; notifications will be skipped")

    # ----------------- Back-compat low-level APIs -----------------

    def slack(self, msg: str):
        """Send a raw Slack message (back-compat)."""
        if not self._slack_url:
            return
        try:
            payload = {"text": msg[:MAX_SLACK_LEN]}
            requests.post(self._slack_url, json=payload, timeout=10)
        except Exception as e:
            logger.error("Slack notify failed: %s", e)

    def email(self, subject: str, body: str, html: str | None = None):
        """Send a raw email (back-compat). If html is provided, sends a multipart email."""
        if not all([self._email_host, self._email_port, self._email_user, self._email_pass, self._email_from, self._email_to]):
            return
        try:
            if html:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body or "", "plain"))
                msg.attach(MIMEText(html, "html"))
            else:
                msg = MIMEText(body or "", "plain")

            msg["Subject"] = subject
            msg["From"] = self._email_from
            msg["To"] = self._email_to

            with smtplib.SMTP(self._email_host, int(self._email_port)) as server:
                server.starttls()
                server.login(self._email_user, self._email_pass)
                server.send_message(msg)
        except Exception as e:
            logger.error("Email send failed: %s", e)

    # ----------------- Higher-level helpers -----------------

    def notify_tender(self, row: Dict[str, Any]):
        """
        Send a formatted 'New Tender' notification to all configured channels.
        Safe no-op if no destinations configured.
        """
        text = self._format_tender_text(row)
        html = self._format_tender_html(row)

        # Slack
        if self._slack_url:
            self.slack(text)

        # Email
        if all([self._email_host, self._email_port, self._email_user, self._email_pass, self._email_from, self._email_to]):
            subject = f"New Tender: {row.get('title') or '[Untitled]'}"
            self.email(subject=subject, body=text, html=html)

    def notify_batch(self, rows: Iterable[Dict[str, Any]], title: str = "New Tenders Digest"):
        """
        Send a digest with multiple tenders. Useful if you want a single summary
        instead of one message per tender.
        """
        rows = [r for r in rows]
        if not rows:
            return

        # Slack digest (plain)
        if self._slack_url:
            parts = [self._format_tender_text(r) for r in rows]
            msg = "\n\n".join(parts)
            if len(msg) > MAX_SLACK_LEN:
                msg = msg[:MAX_SLACK_LEN] + "\n…(truncated)"
            self.slack(msg)

        # Email digest (HTML + plain)
        if all([self._email_host, self._email_port, self._email_user, self._email_pass, self._email_from, self._email_to]):
            html_items = "\n".join(self._format_tender_html(r) for r in rows)
            html = f"<h3>{title}</h3>\n{html_items}"
            plain = "\n\n".join(self._format_tender_text(r) for r in rows)
            self.email(subject=title, body=plain, html=html)

    # ----------------- Formatting -----------------

    @staticmethod
    def _format_tender_text(row: Dict[str, Any]) -> str:
        title = row.get("title") or "[Untitled]"
        buyer = row.get("buyer") or "-"
        closes = row.get("closing_ts") or row.get("closing_date") or "-"
        portal = row.get("source_portal") or "-"
        link = row.get("link") or "-"
        value = row.get("tender_value")
        value_str = f"${value:,.2f}" if isinstance(value, (int, float)) else "-"

        lines = [
            f"*New Tender*: {title}",
            f"Buyer: {buyer}",
            f"Closes: {closes}",
            f"Value: {value_str}",
            f"Source: {portal}",
            f"Link: {link}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_tender_html(row: Dict[str, Any]) -> str:
        title = (row.get("title") or "[Untitled]").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        buyer = (row.get("buyer") or "-")
        closes = row.get("closing_ts") or row.get("closing_date") or "-"
        portal = row.get("source_portal") or "-"
        link = row.get("link") or "#"
        value = row.get("tender_value")
        value_str = f"${value:,.2f}" if isinstance(value, (int, float)) else "-"

        return (
            "<div style='margin:12px 0;padding:10px;border:1px solid #eee;border-radius:8px;'>"
            f"<div style='font-weight:600;font-size:16px;margin-bottom:4px;'>{title}</div>"
            f"<div><b>Buyer:</b> {buyer}</div>"
            f"<div><b>Closes:</b> {closes}</div>"
            f"<div><b>Value:</b> {value_str}</div>"
            f"<div><b>Source:</b> {portal}</div>"
            f"<div><a href='{link}'>View opportunity</a></div>"
            "</div>"
        )

