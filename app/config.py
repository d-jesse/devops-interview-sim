from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://10.0.0.58:11434"
    grading_model: str = "qwen3.6:35b"
    question_bank_path: Path = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"


settings = Settings()
