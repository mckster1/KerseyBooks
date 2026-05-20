from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import sqlite3

from .database import init_db, get_db, DB_PATH
from .routers import accounts, journal_entries, reports, imports, ask, settings

# ── Seed data ─────────────────────────────────────────────────────────────────

CHART_OF_ACCOUNTS = [
    # code, name, type, normal_balance
    ("1000", "Checking Account",          "asset",     "debit"),
    ("1010", "Petty Cash",                "asset",     "debit"),
    ("1020", "Accounts Receivable",       "asset",     "debit"),
    ("2000", "Business Credit Card",      "liability", "credit"),
    ("2010", "Mortgage Payable",          "liability", "credit"),
    ("3000", "Owner Equity",              "equity",    "credit"),
    ("3010", "Owner Draws",               "equity",    "debit"),
    ("3020", "Retained Earnings",         "equity",    "credit"),
    ("4000", "Car Wash Revenue",          "income",    "credit"),
    ("4010", "Laundromat Revenue",        "income",    "credit"),
    ("4020", "Other Income",              "income",    "credit"),
    ("5000", "Cost of Goods / Supplies",  "expense",   "debit"),
    ("5010", "Utilities",                 "expense",   "debit"),
    ("5020", "Repairs & Maintenance",     "expense",   "debit"),
    ("5030", "Insurance",                 "expense",   "debit"),
    ("5040", "Mortgage Interest",         "expense",   "debit"),
    ("5050", "Advertising & Marketing",   "expense",   "debit"),
    ("5060", "Professional Services",     "expense",   "debit"),
    ("5070", "Bank Fees & Merchant Fees", "expense",   "debit"),
    ("5080", "Vehicle & Travel",          "expense",   "debit"),
    ("5090", "Meals & Entertainment",     "expense",   "debit"),
    ("5100", "Office Supplies",           "expense",   "debit"),
    ("5110", "Wages & Labor",             "expense",   "debit"),
    ("5120", "Payroll Taxes",             "expense",   "debit"),
    ("5130", "Miscellaneous",             "expense",   "debit"),
]


def seed_accounts(db: sqlite3.Connection):
    for code, name, acct_type, normal_balance in CHART_OF_ACCOUNTS:
        existing = db.execute("SELECT id FROM accounts WHERE code = ?", (code,)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO accounts (code, name, type, normal_balance) VALUES (?,?,?,?)",
                (code, name, acct_type, normal_balance),
            )
    db.commit()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="KerseyBooks",
    description="Double-entry bookkeeping for Kersey Car Wash & Kersey Laundromat",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(journal_entries.router)
app.include_router(reports.router)
app.include_router(imports.router)
app.include_router(ask.router)
app.include_router(settings.router)


@app.on_event("startup")
def startup():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    seed_accounts(conn)
    conn.close()
    print(f"[OK] KerseyBooks running -- DB: {DB_PATH}")


@app.get("/api/backup")
def download_backup():
    if not Path(DB_PATH).exists():
        raise HTTPException(404, "Database file not found")
    # Flush the WAL into the main .db file so the downloaded copy is complete
    _conn = sqlite3.connect(DB_PATH)
    try:
        _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        _conn.close()
    return FileResponse(
        path=DB_PATH,
        filename="kersey_backup.db",
        media_type="application/octet-stream",
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "db": DB_PATH}


# Serve dashboard as root
_dashboard = Path(__file__).parent.parent.parent / "dashboard"
if _dashboard.exists():
    app.mount("/", StaticFiles(directory=str(_dashboard), html=True), name="dashboard")
