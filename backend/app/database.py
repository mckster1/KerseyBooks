import sqlite3
import os
from pathlib import Path

# DB path: env override, else sibling of backend/ named kersey.db
_DEFAULT_DB = str(Path(__file__).parent.parent.parent / "kersey.db")
DB_PATH = os.getenv("DB_PATH", _DEFAULT_DB)


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
