import requests
import smtplib
from email.mime.text import MIMEText
from utils.config import Config
from utils.logger import logger

class Notifier:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def slack(self, msg: str):
        if not self.cfg.slack_webhook_url:
            return
        try:
            requests.post(self.cfg.slack_webhook_url, json={"text": msg}, timeout=10)
        except Exception as e:
            logger.error("Slack notify failed: %s", e)

    def email(self, subject: str, body: str):
        if not (self.cfg.email_host and self.cfg.email_user and self.cfg.email_pass and self.cfg.email_from and self.cfg.email_to):
            return
        try:
            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["From"] = self.cfg.email_from
            msg["To"] = self.cfg.email_to
            with smtplib.SMTP(self.cfg.email_host, self.cfg.email_port) as server:
                server.starttls()
                server.login(self.cfg.email_user, self.cfg.email_pass)
                server.send_message(msg)
        except Exception as e:
            logger.error("Email send failed: %s", e)
