"""Standalone script to seed the chart of accounts (also runs on app startup)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.database import get_connection, init_db
from app.main import seed_accounts

if __name__ == "__main__":
    print("Initializing database schema...")
    init_db()
    conn = get_connection()
    print("Seeding chart of accounts...")
    seed_accounts(conn)
    conn.close()
    print("Done — chart of accounts seeded.")
