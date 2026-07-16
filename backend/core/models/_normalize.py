import re


def normalize_merchant(value: str | None) -> str:
    if value is None or not value.strip():
        return ""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()    
