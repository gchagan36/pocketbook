from enum import StrEnum


class AccountType(StrEnum):
    CASH = "cash"
    CHECKING = "checking"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    LOAN = "loan"
    OTHER = "other"
    SAVINGS = "savings"


class BudgetPeriod(StrEnum):
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    YEARLY = "yearly"


class MatchType(StrEnum):
    CONTAINS = "contains"
    EQUALS = "equals"
    FUZZY = "fuzzy"
    REGEX = "regex"


class RuleField(StrEnum):
    DESCRIPTION = "description"
    MERCHANT = "merchant"


class TransactionStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    