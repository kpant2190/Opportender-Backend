
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Tender:
    title: str
    description: str
    category: Optional[str]
    closing_date: Optional[str]
    buyer: Optional[str]
    link: str
    contact_name: Optional[str]
    contact_email: Optional[str]
    tender_value: Optional[float]
    source_portal: str
    atm_id: Optional[str] = None  # future-proof

    def to_row(self) -> dict:
        # No embedding here anymore
        return {
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "closing_date": self.closing_date,
            "buyer": self.buyer,
            "link": self.link,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "tender_value": self.tender_value,
            "source_portal": self.source_portal,
            "embedding": None,
            "atm_id": self.atm_id,
        }

class BaseScraper:
    name: str = "base"
    async def fetch(self) -> List[Tender]:
        raise NotImplementedError
