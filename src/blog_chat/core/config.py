from pathlib import Path
from urllib.parse import urlparse
import os
from dotenv import load_dotenv
load_dotenv()


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

CONTENT_DIR = Path("content")
if not CONTENT_DIR.exists():
    raise ValueError(f"Content directory {CONTENT_DIR} does not exist")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///chat.db")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")
if not DATABASE_URL.startswith("sqlite+aiosqlite://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise ValueError(
        "DATABASE_URL must compatible with either SQLite or PostgreSQL (e.g., sqlite+aiosqlite:///chat.db or postgresql+asyncpg://user:password@localhost/dbname)"
    )

SITE_URL = os.environ.get("SITE_URL", "https://blog.chrislabs.net")

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET environment variable is required")

APP_ENV = os.environ.get("APP_ENV", "development")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("LOG_FORMAT", "json" if APP_ENV != "development" else "console")

UMAMI_ENABLED = _env_bool("UMAMI_ENABLED", "true")
UMAMI_SCRIPT_URL = os.environ.get(
    "UMAMI_SCRIPT_URL",
    "https://latitudem2m-analytics.chrislabs.net/script.js",
)
UMAMI_RECORDER_URL = os.environ.get(
    "UMAMI_RECORDER_URL",
    "https://latitudem2m-analytics.chrislabs.net/recorder.js",
)
UMAMI_WEBSITE_ID = os.environ.get("UMAMI_WEBSITE_ID", "")

UMAMI_HOST = ""
if UMAMI_SCRIPT_URL:
    UMAMI_HOST = urlparse(UMAMI_SCRIPT_URL).netloc
UMAMI_RECORDER_HOST = ""
if UMAMI_RECORDER_URL:
    UMAMI_RECORDER_HOST = urlparse(UMAMI_RECORDER_URL).netloc
UMAMI_ACTIVE = UMAMI_ENABLED and bool(UMAMI_WEBSITE_ID)
