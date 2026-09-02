from __future__ import annotations

from dataclasses import dataclass
import os


class ConfigurationError(ValueError):
    """Raised when required application configuration is missing or invalid."""


def _required(name: str) -> str:
    value = os.getenv(name)

    if value is None or not value.strip():
        raise ConfigurationError(f"{name} is required")

    return value.strip()


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be a positive number"
        ) from exc

    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than 0")

    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be a positive integer"
        ) from exc

    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than 0")

    return value


@dataclass(frozen=True)
class Settings:
    claude_model: str
    anthropic_api_key: str
    razorpay_key_id: str
    razorpay_key_secret: str
    mandate_secret_key: bytes
    database_path: str
    mandate_ttl_seconds: int
    max_retries: int
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "Settings":
        mandate_secret_raw = _required("MANDATE_SECRET_KEY")

        try:
            mandate_secret_key = mandate_secret_raw.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ConfigurationError(
                "MANDATE_SECRET_KEY must be valid UTF-8"
            ) from exc

        if len(mandate_secret_key) < 32:
            raise ConfigurationError(
                "MANDATE_SECRET_KEY must be at least 32 bytes"
            )

        database_path = os.getenv("DATABASE_PATH", "state.db").strip()

        if not database_path:
            raise ConfigurationError("DATABASE_PATH cannot be empty")
            

        return cls(
            claude_model=_required("CLAUDE_MODEL"),
            anthropic_api_key=_required("ANTHROPIC_API_KEY"),
            razorpay_key_id=_required("RAZORPAY_KEY_ID"),
            razorpay_key_secret=_required("RAZORPAY_KEY_SECRET"),
            mandate_secret_key=mandate_secret_key,
            database_path=database_path,
            mandate_ttl_seconds=_positive_int(
                "MANDATE_TTL_SECONDS",
                300,
            ),
            max_retries=_positive_int(
                "MAX_RETRIES",
                3,
            ),
            request_timeout_seconds=_positive_float(
                "REQUEST_TIMEOUT_SECONDS",
                10.0,
            ),
        )