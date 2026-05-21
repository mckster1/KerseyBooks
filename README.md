# KerseyBooks

Double-entry bookkeeping for **Kersey Car Wash** and **Kersey Laundromat** — two DBAs, one owner, one database.

Replaces Patriot Software. Built on FastAPI + SQLite. No cloud, no subscription.

---

## Quick Start (Windows)

Double-click:

```text
Launch KerseyBooks.bat
```

Or run manually:

```powershell
cd C:\Users\Name\Desktop\KerseyBooks
.\scripts\start.ps1
```

The batch launcher starts the backend and opens **http://localhost:8001** in your browser.

On first run the script will:
1. Copy `.env.example` → `.env`
2. Create a Python virtual environment in `.venv/`
3. Install dependencies from `backend/requirements.txt`
4. Start the server on port **8001**

---

## Manual Setup

```powershell
# From KerseyBooks root
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt

# Edit .env - add LLM_API_KEY if using Ask AI
Copy-Item .env.example .env
notepad .env

# Start server
cd backend
.\..\venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `./kersey.db` | Path to SQLite database |
| `LLM_PROVIDER` | `anthropic` | AI provider: `anthropic`, `openai`, or `openai-compatible` |
| `LLM_MODEL` | provider default | Model used by Ask AI and Plaid suggestions |
| `LLM_API_KEY` | *(empty)* | Required for Ask AI and AI-assisted Plaid suggestions |
| `LLM_BASE_URL` | OpenAI default | Optional base URL for OpenAI-compatible providers |
| `CORS_ORIGINS` | `http://localhost:8001` | Allowed CORS origins |

---

## Project Structure

```
KerseyBooks/
├── .env.example          — Environment template
├── .gitignore            — Excludes *.db, .env, __pycache__, .venv
├── README.md
├── backend/
│   ├── requirements.txt
│   ├── schema.sql        — SQLite schema reference
│   ├── seed_accounts.py  — Standalone seeder (also runs on startup)
│   └── app/
│       ├── main.py       — FastAPI app, startup, /api/backup, /api/health
│       ├── database.py   — SQLite connection management
│       ├── models.py     — Pydantic request/response models
│       └── routers/
│           ├── accounts.py        — GET/POST/PUT /api/accounts
│           ├── journal_entries.py — GET/POST/DELETE /api/journal-entries
│           ├── reports.py         — P&L, Balance Sheet, Cash Flow, etc.
│           ├── imports.py         — POST /api/import/csv
│           └── ask.py             — POST /api/ask (AI Q&A)
├── dashboard/
│   └── index.html        — Single-file dashboard (served at /)
└── scripts/
    └── start.ps1         — Windows launcher
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/accounts` | List chart of accounts |
| POST | `/api/accounts` | Create account |
| PUT | `/api/accounts/{id}` | Update account |
| GET | `/api/journal-entries` | List entries (filters: start, end, dba, account) |
| POST | `/api/journal-entries` | Create entry (validates debits == credits) |
| DELETE | `/api/journal-entries/{id}` | Delete entry |
| GET | `/api/reports/pl` | Profit & Loss (`?start=&end=&dba=`) |
| GET | `/api/reports/balance-sheet` | Balance Sheet (`?as_of=&dba=`) |
| GET | `/api/reports/cash-flow` | Cash Flow (`?start=&end=&dba=`) |
| GET | `/api/reports/expense-categories` | Expenses by category |
| GET | `/api/reports/month-over-month` | Monthly P&L comparison (`?year=&dba=`) |
| POST | `/api/import/csv` | Import CSV transactions |
| POST | `/api/import/csv/preview` | Preview CSV without importing |
| POST | `/api/ask` | AI Q&A with financial context |
| GET | `/api/backup` | Download database file |
| GET | `/api/health` | Health check |

---

## DBA Tags

Every journal entry is tagged with one of:

| Tag | Meaning |
|---|---|
| `carwash` | Kersey Car Wash only |
| `laundromat` | Kersey Laundromat only |
| `shared` | Shared expense (both DBAs) |
| `both` | Applies to both (e.g. combined deposit) |

All reports are filterable by DBA.

---

## Accounting Model

Standard double-entry bookkeeping:

- Every transaction is a **journal entry** with debit and credit **lines**
- Sum of debits **must equal** sum of credits (enforced by the API)
- Normal balances follow GAAP: Assets/Expenses = Debit, Liabilities/Equity/Income = Credit

---

## Bank Feed

KerseyBooks includes a Plaid-powered bank feed for low-cost transaction automation.

1. Add `PLAID_CLIENT_ID`, `PLAID_SECRET`, and `PLAID_ENV` in `.env`, or save them in Settings under **Plaid Bank Feed**.
2. Open **Bank Feed** and click **Connect Bank**.
3. Map each connected Plaid account to the matching bookkeeping account, usually Checking Account `1000`.
4. Click **Sync** to pull new bank activity into the pending review queue.
5. Review each pending transaction, adjust account/DBA if needed, then **Post** it to create a balanced journal entry.

Pending Plaid transactions do not affect reports until they are posted.

---
## Backup

The `.db` file **is** the backup. Download or copy it anytime:

- Click **Backup DB** in the header
- Or: `GET http://localhost:8001/api/backup`
- Or: copy `kersey.db` directly

The database is excluded from git. Keep regular copies.

### Google Drive For Desktop Backup

The simplest cloud backup is to use Google Drive for desktop:

1. Install Google Drive for desktop and sign in to the Drive account that should hold backups.
2. Create a folder such as `KerseyBooks Backups` inside the synced Drive folder.
3. In KerseyBooks Settings, paste that folder path into **Database Backup**.
4. Click **Copy to Backup Folder**.

KerseyBooks will create timestamped files like `kersey_backup_20260521_143000.db`.
Google Drive for desktop handles the upload and sharing.

---

## CSV Import Format

Patriot GL export columns (auto-detected):

```
Date, Description, Debit, Credit, Reference, Account
```

Simple bank export (also supported):

```
Date, Description, Amount
```

Date formats accepted: `MM/DD/YYYY`, `YYYY-MM-DD`, `MM/DD/YY`


