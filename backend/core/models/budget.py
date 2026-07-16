from datetime import date

from pydantic import BaseModel

from backend.core.models.enums import BudgetPeriod


class Budget(BaseModel):
    """"""
    id: str
    amount_cents: int
    category_id: str
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    rollover: bool = False
    start_date: date | None = None