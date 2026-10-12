from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LMS_", extra="ignore")

    database_url: str = "postgresql+psycopg://lms:lms@127.0.0.1:5432/lms"
    # Whose "today" decides what is current, expiring or lapsed.
    timezone: str = "Australia/Melbourne"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"LMS_TIMEZONE {value!r} is not a time zone, e.g. Australia/Melbourne")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
