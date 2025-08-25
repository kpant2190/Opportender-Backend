from __future__ import annotations
# tenderbot/scrapers/__init__.py

from .static_example_scraper import StaticExampleFeed
from .austender_scraper import AusTenderScraper
from .qtenders_scraper import QTendersScraper

# Register all available scrapers
SCRAPERS = {
    "static_example": StaticExampleFeed,
    "austender": AusTenderScraper,
    "qtenders": QTendersScraper,
}

__all__ = [
    "StaticExampleFeed",
    "AusTenderScraper", 
    "QTendersScraper",
    "SCRAPERS"
]

