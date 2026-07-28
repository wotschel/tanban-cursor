import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

DEVELOPMENT_SECRET = "dev-secret-change-me"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
CURSOR_RUNTIMES = frozenset({"cloud", "local"})
ENV_FILE = Path(__file__).with_name(".env")


def load_environment(env_file: str | Path = ENV_FILE) -> None:
    load_dotenv(dotenv_path=env_file, override=False)


def parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise RuntimeError(f"{name} must be a boolean value (true/false)")


def parse_optional_positive_int(name: str, value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value.strip())
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if parsed < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class Settings:
    app_env: str
    secret_key: str
    database_url: str
    tanban_base_url: str
    tanban_api_key: str
    tanban_webhook_secret: str
    tanban_board_id: int | None
    cursor_api_key: str
    cursor_model: str
    cursor_runtime: str
    cursor_repository: str
    activity_log_path: str

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() == "production"


def load_settings() -> Settings:
    load_environment()
    app_env = os.environ.get("APP_ENV", "development").strip() or "development"
    secret_key = os.environ.get("SECRET_KEY", "").strip()
    if not secret_key:
        if app_env.casefold() == "production":
            raise RuntimeError("SECRET_KEY must be set in production")
        secret_key = DEVELOPMENT_SECRET

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    make_url(database_url)  # validate early

    cursor_runtime = (os.environ.get("CURSOR_RUNTIME") or "cloud").strip().casefold()
    if cursor_runtime not in CURSOR_RUNTIMES:
        raise RuntimeError("CURSOR_RUNTIME must be cloud or local")

    return Settings(
        app_env=app_env,
        secret_key=secret_key,
        database_url=database_url,
        tanban_base_url=(os.environ.get("TANBAN_BASE_URL") or "").strip().rstrip("/"),
        tanban_api_key=(os.environ.get("TANBAN_API_KEY") or "").strip(),
        tanban_webhook_secret=(os.environ.get("TANBAN_WEBHOOK_SECRET") or "").strip(),
        tanban_board_id=parse_optional_positive_int("TANBAN_BOARD_ID", os.environ.get("TANBAN_BOARD_ID")),
        cursor_api_key=(os.environ.get("CURSOR_API_KEY") or "").strip(),
        cursor_model=(os.environ.get("CURSOR_MODEL") or "composer-2.5").strip() or "composer-2.5",
        cursor_runtime=cursor_runtime,
        cursor_repository=(os.environ.get("CURSOR_REPOSITORY") or "").strip(),
        activity_log_path=(os.environ.get("ACTIVITY_LOG_PATH") or "./volumes/logs/activity.log").strip(),
    )


settings = load_settings()
