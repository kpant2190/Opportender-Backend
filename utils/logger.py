from __future__ import annotations
# tenderbot/utils/logger.py
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _build_logger() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log = logging.getLogger("tenderbot")
    if log.handlers:
        # Already configured (avoid duplicate handlers if module is imported multiple times)
        return log

    log.setLevel(level)

    fmt = os.getenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s %(name)s %(message)s")
    datefmt = os.getenv("LOG_DATEFMT", "%Y-%m-%d %H:%M:%S")

    # Console handler (stdout)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    log.addHandler(sh)

    # Optional file logging with rotation
    log_file = os.getenv("LOG_FILE", "").strip()
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
        except Exception:
            # If directory isn't provided or cannot be created, fall back silently
            pass
        fh = RotatingFileHandler(
            log_file,
            maxBytes=int(os.getenv("LOG_FILE_MAX_BYTES", str(5 * 1024 * 1024))),  # 5 MB
            backupCount=int(os.getenv("LOG_FILE_BACKUP_COUNT", "3")),
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        log.addHandler(fh)

    # Tame noisy third-party loggers (override with *_LOG_LEVEL envs if needed)
    def quiet_logger(name: str, default: str = "WARNING"):
        lvl = getattr(logging, os.getenv(f"{name.upper().replace('.', '_')}_LOG_LEVEL", default).upper(), None)
        if lvl is not None:
            logging.getLogger(name).setLevel(lvl)

    for noisy in ("httpx", "urllib3", "openai", "playwright", "requests"):
        quiet_logger(noisy)

    return log


logger = _build_logger()

