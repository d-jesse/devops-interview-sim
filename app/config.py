from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://10.0.0.58:11434"
    grading_model: str = "qwen3.6:35b"
    question_bank_path: Path = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"

    db_path: Path = Path(__file__).resolve().parent.parent / "data" / "app.db"

    session_cookie_name: str = "dis_session"
    session_ttl_days: int = 30

    admin_email: str = "admin@admin"
    admin_password: str = "changeme123"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8010/api/auth/google/callback"


settings = Settings()
