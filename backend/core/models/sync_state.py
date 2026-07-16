from datetime import datetime

from pydantic import BaseModel


class SyncState(BaseModel):
    """"""
    provider: str
    cursor: str | None = None
    error_count: int = 0
    last_error: str | None = None
    last_run_at: datetime | None = None