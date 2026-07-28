import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

from services.tanban_boards import (
    LegacyBoardBinding,
    TanbanBoardConfig,
    TanbanBoardsConfigError,
    boards_from_legacy,
    parse_boards_json,
    resolve_board,
)

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
    tanban_boards: dict[str, TanbanBoardConfig]
    tanban_legacy: LegacyBoardBinding | None
    cursor_active: bool
    cursor_api_key: str
    cursor_model: str
    cursor_runtime: str
    cursor_repository: str
    activity_log_path: str

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() == "production"

    def resolve_board(self, board_public_id: str | None) -> TanbanBoardConfig | LegacyBoardBinding | None:
        """Return credentials for a webhook board public_id."""
        return resolve_board(self.tanban_boards, self.tanban_legacy, board_public_id)

    def webhook_secrets(self) -> list[str]:
        secrets: list[str] = []
        for board in self.tanban_boards.values():
            if board.webhook_secret:
                secrets.append(board.webhook_secret)
        if self.tanban_legacy and self.tanban_legacy.webhook_secret:
            secrets.append(self.tanban_legacy.webhook_secret)
        return secrets

    @property
    def tanban_webhook_secret(self) -> str:
        """Backward-compatible single secret (first configured). Prefer ``resolve_board``."""
        secrets = self.webhook_secrets()
        return secrets[0] if secrets else ""

    @property
    def tanban_board_id(self) -> int | None:
        if len(self.tanban_boards) == 1:
            return next(iter(self.tanban_boards.values())).board_id
        if self.tanban_legacy is not None:
            return self.tanban_legacy.board_id
        return None

    @property
    def tanban_api_key(self) -> str:
        if len(self.tanban_boards) == 1:
            return next(iter(self.tanban_boards.values())).api_key
        if self.tanban_legacy is not None:
            return self.tanban_legacy.api_key
        return ""


def _load_board_settings() -> tuple[dict[str, TanbanBoardConfig], LegacyBoardBinding | None]:
    raw_boards = (os.environ.get("TANBAN_BOARDS") or "").strip()
    legacy_board_id = parse_optional_positive_int("TANBAN_BOARD_ID", os.environ.get("TANBAN_BOARD_ID"))
    legacy_api_key = (os.environ.get("TANBAN_API_KEY") or "").strip()
    legacy_secret = (os.environ.get("TANBAN_WEBHOOK_SECRET") or "").strip()
    legacy_public_id = (os.environ.get("TANBAN_BOARD_PUBLIC_ID") or "").strip()

    if raw_boards:
        try:
            boards = parse_boards_json(raw_boards)
        except TanbanBoardsConfigError as error:
            raise RuntimeError(str(error)) from error
        return boards, None

    # Prefer explicit public_id + legacy vars as a one-entry map.
    boards = boards_from_legacy(
        board_id=legacy_board_id,
        api_key=legacy_api_key,
        webhook_secret=legacy_secret,
        board_public_id=legacy_public_id or None,
    )
    if boards:
        return boards, None

    if legacy_board_id is not None or legacy_api_key or legacy_secret:
        return {}, LegacyBoardBinding(
            board_id=legacy_board_id,
            api_key=legacy_api_key,
            webhook_secret=legacy_secret,
        )
    return {}, None


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

    cursor_active_raw = (os.environ.get("CURSOR_ACTIVE") or "false").strip() or "false"
    tanban_boards, tanban_legacy = _load_board_settings()

    return Settings(
        app_env=app_env,
        secret_key=secret_key,
        database_url=database_url,
        tanban_base_url=(os.environ.get("TANBAN_BASE_URL") or "").strip().rstrip("/"),
        tanban_boards=tanban_boards,
        tanban_legacy=tanban_legacy,
        cursor_active=parse_bool("CURSOR_ACTIVE", cursor_active_raw),
        cursor_api_key=(os.environ.get("CURSOR_API_KEY") or "").strip(),
        cursor_model=(os.environ.get("CURSOR_MODEL") or "composer-2.5").strip() or "composer-2.5",
        cursor_runtime=cursor_runtime,
        cursor_repository=(os.environ.get("CURSOR_REPOSITORY") or "").strip(),
        activity_log_path=(os.environ.get("ACTIVITY_LOG_PATH") or "./volumes/logs/activity.log").strip(),
    )


settings = load_settings()
