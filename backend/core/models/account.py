from pydantic import BaseModel

from backend.core.models.enums import AccountType


class Account(BaseModel):
    """"""
    id: str
    balance_cents: int | None = None
    currency: str = "USD"
    external_id: str | None = None
    institution: str | None = None
    name: str
    source: str
    type: AccountType = AccountType.OTHER