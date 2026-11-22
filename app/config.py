from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No hardcoded defaults for these three: a missing .env should fail
    # loudly at startup, not silently fall back to a well-known admin
    # password or someone else's Tailscale address on a public deployment.
    ollama_base_url: str
    admin_email: str
    admin_password: str

    grading_model: str = "qwen3.6:35b"
    question_bank_path: Path = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"

    db_path: Path = Path(__file__).resolve().parent.parent / "data" / "app.db"

    session_cookie_name: str = "dis_session"
    session_ttl_days: int = 30

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8010/api/auth/google/callback"


settings = Settings()
