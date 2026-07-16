from pydantic import BaseModel

from backend.core.models.enums import MatchType, RuleField


class CategoryRule(BaseModel):
    """"""
    id: str
    category_id: str
    field: RuleField = RuleField.MERCHANT
    match_type: MatchType = MatchType.CONTAINS
    pattern: str
    priority: int = 0