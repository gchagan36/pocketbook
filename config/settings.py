from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Behavior (non-secret defaults, env-overridable) ---
    active_providers: list[str] = Field(default_factory=lambda: ["csv_import"])
    sync_interval_seconds: int = 3600
    categorization_confidence_threshold: float = 0.8
    db_path: Path = Path("./pocketbook.db")

    # --- Plaid (optional; required only when "plaid" is active) ---
    plaid_client_id: str | None = None
    plaid_client_secret: SecretStr | None = None
    plaid_env: Literal["sandbox", "development", "production"] = "sandbox"

    # --- Secrets ---
    token_vault_key: SecretStr | None = None
    api_auth_token: SecretStr | None = None


settings = Settings()
