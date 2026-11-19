from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    api_id: int = Field(gt=0)
    api_hash: SecretStr
    bot_token: SecretStr
    owner_id: int = Field(gt=0)
    assistant_sessions: SecretStr = SecretStr('')
    assistant_sessions_file: str | None = None
    assistant_key: SecretStr | None = None
    database_url: str = 'sqlite+aiosqlite:///./akshita.db'
    max_queue: int = Field(default=100, ge=1, le=1000)
    extraction_concurrency: int = Field(default=3, ge=1, le=20)
    video_enabled: bool = False
    log_level: str = 'INFO'

    @field_validator('database_url')
    @classmethod
    def async_database(cls, value: str) -> str:
        if not value.startswith(('sqlite+aiosqlite:///', 'postgresql+asyncpg://')):
            raise ValueError('Use sqlite+aiosqlite or postgresql+asyncpg')
        return value

    def sessions(self) -> list[str]:
        raw = self.assistant_sessions.get_secret_value()
        if self.assistant_sessions_file:
            if raw or not self.assistant_key:
                raise ValueError('Specify either assistant sessions or an encrypted file and key')
            try:
                raw = Fernet(self.assistant_key.get_secret_value().encode()).decrypt(
                    Path(self.assistant_sessions_file).read_bytes()
                ).decode('utf-8')
            except (ValueError, InvalidToken, OSError, UnicodeError) as exc:
                raise ValueError('Could not decrypt assistant session file') from exc
        sessions = [s.strip() for s in raw.split(',') if s.strip()]
        if not 1 <= len(sessions) <= 10 or len(set(sessions)) != len(sessions):
            raise ValueError('Provide 1–10 distinct assistant sessions')
        return sessions
