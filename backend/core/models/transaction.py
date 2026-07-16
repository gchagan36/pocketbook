import hashlib
from datetime import date

from pydantic import BaseModel

from backend.core.models._normalize import normalize_merchant
from backend.core.models.enums import TransactionStatus


class Transaction(BaseModel):
    """"""
    id: str
    account_id: str
    amount_cents: int
    category_confidence: float | None = None
    category_id: str | None = None
    currency: str = "USD"
    date: date
    description: str | None = None
    external_id: str | None = None
    merchant: str | None = None
    needs_review: bool = True
    status: TransactionStatus = TransactionStatus.POSTED
    source: str

    def fingerprint(self) -> str:
        raw = f"{self.account_id}|{self.amount_cents}|{self.date.isoformat()}|{normalize_merchant(self.merchant)}"
        return hashlib.sha256(raw.encode()).hexdigest()