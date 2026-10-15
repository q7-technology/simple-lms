import re
import urllib.parse
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class Settings(BaseSettings):
    """What .env says. The everyday settings below (time zone, web address,
    email, daily hour, quiz wait) are only the fallback: read them through
    lms/services/settings.py, where a value set on the Settings screen wins."""
    model_config = SettingsConfigDict(env_prefix="LMS_", extra="ignore")

    database_url: str = "postgresql+psycopg://lms:lms@127.0.0.1:5432/lms"
    # Whose "today" decides what is current, expiring or lapsed, and when the
    # daily job runs.
    timezone: str = "Australia/Melbourne"

    # Tickets' photos and policy signatures: kept on disk (a volume in
    # Compose), named by a random id. Only the API reads and writes them.
    upload_dir: str = "/data/uploads"

    # Where people open Simple LMS, for the links in emails, e.g.
    # https://lms.example.com.au. Without it the emails carry no link.
    public_url: str = ""

    # Signing in with Microsoft Entra ID: the app registered in your tenant
    # (README). All three, and a web address (Settings, or LMS_PUBLIC_URL),
    # or the button never shows. In .env only: a secret, kept off the screen.
    # The tenant is yours alone, by its id: not common or organizations.
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    # kept out of repr(), so printing the settings never shows it
    entra_client_secret: str = Field(default="", repr=False)
    # Microsoft's sign-in address; changed only to try it against a stand-in
    entra_authority: str = "https://login.microsoftonline.com"

    # Email, sent by the worker. Without a host the emails wait, unsent,
    # until one is set.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    # starttls (port 587), ssl (port 465) or none (a relay on the same network)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"

    # The worker: how long it waits when there is nothing to send, and the
    # hour (in LMS_TIMEZONE) from which it runs the daily job each day.
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    daily_hour: int = Field(default=6, ge=0, le=23)

    # After a few goes at a module's quiz in a row that didn't pass (3 unless
    # Settings says otherwise), how long the learner waits before the next,
    # e.g. 1440 for a day. 0: no wait.
    quiz_cooldown_minutes: int = Field(default=60, ge=0)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"LMS_TIMEZONE {value!r} is not a time zone, e.g. Australia/Melbourne")
        return value

    @field_validator("public_url", "entra_authority")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("entra_authority")
    @classmethod
    def _authority_is_https(cls, value: str) -> str:
        # after _no_trailing_slash: validators on a field run in order
        parts = urllib.parse.urlsplit(value)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError(f"LMS_ENTRA_AUTHORITY {value!r} must be an https:// address with "
                             "a host, e.g. https://login.microsoftonline.com")
        return value

    @field_validator("entra_tenant_id")
    @classmethod
    def _one_tenant(cls, value: str) -> str:
        value = value.strip().lower()
        if value and not re.fullmatch(GUID, value):
            raise ValueError(f"LMS_ENTRA_TENANT_ID {value!r} must be your Directory (tenant) "
                             "ID, a GUID: not common, organizations or a domain name")
        return value

    @field_validator("entra_client_id")
    @classmethod
    def _client_is_a_guid(cls, value: str) -> str:
        value = value.strip().lower()
        if value and not re.fullmatch(GUID, value):
            raise ValueError(f"LMS_ENTRA_CLIENT_ID {value!r} must be the app's Application "
                             "(client) ID, a GUID")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
