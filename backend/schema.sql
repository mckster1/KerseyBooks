-- KerseyBooks SQLite Schema
-- Double-entry bookkeeping for Kersey Car Wash & Kersey Laundromat

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL,
    type           TEXT    NOT NULL CHECK(type IN ('asset','liability','equity','income','expense')),
    normal_balance TEXT    NOT NULL CHECK(normal_balance IN ('debit','credit')),
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,  -- ISO date YYYY-MM-DD
    description TEXT    NOT NULL,
    reference   TEXT,
    dba         TEXT    NOT NULL CHECK(dba IN ('carwash','laundromat','shared','both')),
    memo        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_id       INTEGER NOT NULL REFERENCES accounts(id),
    debit            REAL    NOT NULL DEFAULT 0.0,
    credit           REAL    NOT NULL DEFAULT 0.0,
    dba_override     TEXT    CHECK(dba_override IN ('carwash','laundromat','shared','both') OR dba_override IS NULL)
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,
    description  TEXT    NOT NULL,
    amount       REAL    NOT NULL,
    account_id   INTEGER REFERENCES accounts(id),
    source       TEXT    NOT NULL DEFAULT 'manual' CHECK(source IN ('import','manual')),
    raw_csv_row  TEXT,
    imported_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS plaid_connections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id          TEXT    NOT NULL UNIQUE,
    access_token     TEXT    NOT NULL,
    institution_id   TEXT,
    institution_name TEXT,
    cursor           TEXT,
    last_synced      TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS plaid_accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id    INTEGER NOT NULL REFERENCES plaid_connections(id) ON DELETE CASCADE,
    plaid_account_id TEXT    NOT NULL UNIQUE,
    name             TEXT    NOT NULL,
    mask             TEXT,
    type             TEXT,
    subtype          TEXT,
    official_name    TEXT,
    kb_account_id    INTEGER REFERENCES accounts(id),
    created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Pending Plaid transactions awaiting review + journal-entry posting
CREATE TABLE IF NOT EXISTS plaid_pending (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    plaid_transaction_id TEXT    NOT NULL UNIQUE,
    plaid_account_id     TEXT,
    connection_id        INTEGER REFERENCES plaid_connections(id),
    date                 TEXT    NOT NULL,
    description          TEXT    NOT NULL,
    merchant_name        TEXT,
    amount               REAL    NOT NULL,  -- Plaid sign: positive = money OUT, negative = money IN
    plaid_category       TEXT,
    suggested_account_id INTEGER REFERENCES accounts(id),
    suggested_dba        TEXT,
    suggested_confidence TEXT    DEFAULT 'low',
    status               TEXT    NOT NULL DEFAULT 'pending'
                                 CHECK(status IN ('pending','posted','skipped')),
    journal_entry_id     INTEGER REFERENCES journal_entries(id),
    created_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_plaid_pending_status ON plaid_pending(status);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_je_date      ON journal_entries(date);
CREATE INDEX IF NOT EXISTS idx_je_dba       ON journal_entries(dba);
CREATE INDEX IF NOT EXISTS idx_jl_entry     ON journal_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_jl_account   ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_date      ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_account   ON transactions(account_id);
