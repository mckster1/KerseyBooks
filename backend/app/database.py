import sqlite3
import os
from pathlib import Path

# DB path: env override, else repo-root kersey.db. Relative DB_PATH values are
# resolved from the repo root so launch location does not create a second DB.
_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB = _ROOT / "kersey.db"
_ENV_DB = os.getenv("DB_PATH")
DB_PATH = str((_ROOT / _ENV_DB).resolve() if _ENV_DB and not Path(_ENV_DB).is_absolute() else Path(_ENV_DB or _DEFAULT_DB).resolve())


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    schema_path = Path(__file__).parent.parent / "schema.sql"
    conn = get_connection()
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
