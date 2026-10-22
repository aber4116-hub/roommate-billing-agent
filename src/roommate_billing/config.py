"""应用配置（从环境变量/.env 读取）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置。

    生产环境只从环境变量/secret 读取；本地开发可放到被 gitignore 的 .env。
    """

    app_env: str = "development"
    app_secret_key: str = "dev-only-change-me"
    app_base_url: str = "http://127.0.0.1:8000"
    database_url: str = "postgresql+psycopg://roommate@127.0.0.1:55432/roommate_billing"
    test_database_url: str | None = None
    session_cookie_secure: bool = False
    session_ttl_hours: int = 168
    session_idle_hours: int = 24
    allow_registration: bool = False
    log_level: str = "INFO"
    llm_enabled: bool = False
    llm_base_url: str = "https://api.example.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "model-with-tool-calling"
    llm_timeout_seconds: float = 30.0
    agent_max_steps: int = 8
    agent_max_input_chars: int = 4000

    @property
    def session_cookie_name(self) -> str:
        return "__Host-rba_session" if self.session_cookie_secure else "rba_session"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
