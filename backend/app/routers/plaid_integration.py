"""
Plaid bank-connection integration for KerseyBooks.

Flow:
  1. POST /api/plaid/link-token        → get a short-lived token for Plaid Link JS widget
  2. POST /api/plaid/exchange-token    → swap public_token → access_token (stored in DB)
  3. POST /api/plaid/sync              → pull new transactions into plaid_pending staging table
  4. GET  /api/plaid/pending           → review queue
  5. POST /api/plaid/post/{id}         → approve + create journal entry
  6. POST /api/plaid/suggest/{id}      → (re-)ask the configured AI for a better suggestion
  7. POST /api/plaid/skip/{id}         → dismiss
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import json

from ..database import get_db
from ..llm import complete_json, get_llm_config

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


# ── Plaid client factory ────────────────────────────────────────────────────

def _plaid_client():
    try:
        import plaid
        from plaid.api import plaid_api
        from plaid.configuration import Configuration
        from plaid.api_client import ApiClient
    except ImportError:
        raise HTTPException(503, "plaid-python not installed — run: pip install plaid-python")

    client_id = os.getenv("PLAID_CLIENT_ID", "")
    secret    = os.getenv("PLAID_SECRET", "")
    env       = os.getenv("PLAID_ENV", "sandbox").lower()

    if not client_id or not secret:
        raise HTTPException(503, "PLAID_CLIENT_ID and PLAID_SECRET must be set in .env")

    host = {
        "production":  plaid.Environment.Production,
        "development": plaid.Environment.Development,
    }.get(env, plaid.Environment.Sandbox)

    cfg = Configuration(host=host, api_key={"clientId": client_id, "secret": secret})
    return plaid_api.PlaidApi(ApiClient(cfg))


# ── Rule-based auto-categorization ─────────────────────────────────────────

# Keyword lists tuned for a small car-wash / laundromat operation
_EXPENSE_RULES = [
    (["electric", "natural gas", "water dept", "utility", "eversource", "national grid",
      "con ed", "pge", "xcel", "dominion", "gas company", "water bill"], "5010"),
    (["repair", "maintenance", "hvac", "plumber", "electrician", "service call",
      "handyman", "technician", "fix"], "5020"),
    (["insurance", "allstate", "state farm", "progressive", "hartford",
      "liability ins", "coverage"], "5030"),
    (["mortgage", "loan payment", "wellsfargo mort", "chase mort", "property loan"], "5040"),
    (["google ads", "facebook ad", "meta ad", "instagram", "advertising",
      "yelp for biz", "marketing", "flyer", "sign"], "5050"),
    (["attorney", "law office", "legal", "accountant", "cpa", "bookkeeping",
      "consulting", "notary"], "5060"),
    (["bank fee", "service charge", "overdraft", "wire fee", "merchant fee",
      "stripe", "square", "paypal", "intuit payment", "monthly maintenance",
      "processing fee", "transaction fee"], "5070"),
    (["fuel", "shell", "bp", "exxon", "chevron", "sunoco", "speedway",
      "gas station", "auto parts", "jiffy lube", "oil change", "vehicle",
      "parking", "toll", "uber", "lyft"], "5080"),
    (["restaurant", "doordash", "grubhub", "ubereats", "mcdonald", "subway",
      "pizza", "diner", "cafe", "starbucks", "coffee", "food", "lunch"], "5090"),
    (["amazon", "staples", "office depot", "officemax", "walmart", "target",
      "best buy", "costco", "office supply", "paper", "ink", "printer"], "5100"),
    (["payroll", "adp", "paychex", "gusto", "direct dep payroll", "employee"], "5110"),
    (["irs", "eftps", "federal tax", "state tax", "payroll tax", "941", "940",
      "sales tax", "dept of revenue"], "5120"),
    (["chemical", "soap", "detergent", "wash supply", "supply co",
      "janitorial", "cleaning supply", "car wash supply"], "5000"),
]


def _suggest(description: str, merchant: str, amount: float, accounts: list) -> dict:
    """Fast, rule-based transaction categorization."""
    text = f"{description} {merchant or ''}".lower()

    # DBA guess from merchant text
    if any(w in text for w in ["car wash", "carwash", "wash bay", "vacuum bay"]):
        dba = "carwash"
    elif any(w in text for w in ["laundromat", "laundry", "coin laundry"]):
        dba = "laundromat"
    else:
        dba = "shared"

    def acct_id(code: str):
        return next((a["id"] for a in accounts if a["code"] == code), None)

    # Plaid sign: negative = money IN (deposit / revenue)
    if amount <= 0:
        code = {"carwash": "4000", "laundromat": "4010"}.get(dba, "4020")
        return {"account_id": acct_id(code), "dba": dba, "confidence": "medium"}

    # Positive = money OUT (expense)
    for keywords, code in _EXPENSE_RULES:
        if any(kw in text for kw in keywords):
            return {"account_id": acct_id(code), "dba": dba, "confidence": "high"}

    return {"account_id": acct_id("5130"), "dba": dba, "confidence": "low"}  # misc


async def _ai_suggest(description: str, merchant: str, amount: float,
                      accounts: list, db: sqlite3.Connection) -> dict:
    """Ask the configured AI provider for a better categorization suggestion."""
    try:
        config = get_llm_config(db)
        direction = "money IN (income/deposit)" if amount <= 0 else f"money OUT of checking (expense), ${abs(amount):.2f}"
        acct_list = "\n".join(f"  {a['code']} - {a['name']} ({a['type']})" for a in accounts)

        prompt = (
            f"Transaction for a small car-wash and laundromat business:\n"
            f"  Merchant: {merchant or description}\n"
            f"  Description: {description}\n"
            f"  Amount: {direction}\n\n"
            f"Chart of accounts:\n{acct_list}\n\n"
            f"Reply with JSON only, no explanation:\n"
            f'{{"account_code": "<best account code>", "dba": "carwash|laundromat|shared", '
            f'"confidence": "high|medium|low", "reason": "<one sentence>"}}'
        )
        data = complete_json(
            config,
            "You categorize bookkeeping transactions and return JSON only.",
            prompt,
            max_tokens=256,
        )
        acct_id = next((a["id"] for a in accounts if a["code"] == data.get("account_code")), None)
        return {
            "account_id":  acct_id,
            "dba":         data.get("dba", "shared"),
            "confidence":  data.get("confidence", "medium"),
            "reason":      data.get("reason", ""),
        }
    except Exception:
        return _suggest(description, merchant, amount, accounts)


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/link-token")
def create_link_token():
    """Create a short-lived Plaid Link token for the frontend widget."""
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products
    from plaid.model.country_code import CountryCode

    client = _plaid_client()
    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        client_name="KerseyBooks",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id="kersey-owner"),
    )
    resp = client.link_token_create(request)
    return {"link_token": resp.link_token}


class ExchangeTokenBody(BaseModel):
    public_token: str
    institution_id: Optional[str] = None
    institution_name: Optional[str] = None
    accounts: Optional[list] = None


@router.post("/exchange-token")
def exchange_token(body: ExchangeTokenBody, db: sqlite3.Connection = Depends(get_db)):
    """Exchange one-time public_token for a durable access_token."""
    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

    client = _plaid_client()
    req  = ItemPublicTokenExchangeRequest(public_token=body.public_token)
    resp = client.item_public_token_exchange(req)

    # Upsert connection
    existing = db.execute("SELECT id FROM plaid_connections WHERE item_id=?",
                          (resp.item_id,)).fetchone()
    if existing:
        db.execute("UPDATE plaid_connections SET access_token=? WHERE item_id=?",
                   (resp.access_token, resp.item_id))
        conn_id = existing["id"]
    else:
        cur = db.execute(
            "INSERT INTO plaid_connections (item_id, access_token, institution_id, institution_name) VALUES (?,?,?,?)",
            (resp.item_id, resp.access_token,
             body.institution_id, body.institution_name),
        )
        conn_id = cur.lastrowid

    # Store account metadata
    for acct in (body.accounts or []):
        db.execute(
            """INSERT INTO plaid_accounts (connection_id, plaid_account_id, name, mask, type, subtype, official_name)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(plaid_account_id) DO UPDATE SET name=excluded.name""",
            (conn_id, acct.get("id"), acct.get("name"), acct.get("mask"),
             acct.get("type"), acct.get("subtype"), acct.get("official_name")),
        )
    db.commit()
    return {"connection_id": conn_id, "institution": body.institution_name}


@router.get("/connections")
def list_connections(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT c.id, c.institution_name, c.institution_id, c.last_synced, c.created_at,
                  COUNT(a.id) AS account_count
           FROM plaid_connections c
           LEFT JOIN plaid_accounts a ON a.connection_id = c.id
           GROUP BY c.id ORDER BY c.created_at DESC"""
    ).fetchall()
    conns = []
    for r in rows:
        r = dict(r)
        r.pop("access_token", None)  # never expose
        pending = db.execute(
            """SELECT COUNT(*) FROM plaid_pending pp
               JOIN plaid_accounts pa ON pa.plaid_account_id = pp.plaid_account_id
               WHERE pa.connection_id = ? AND pp.status = 'pending'""",
            (r["id"],),
        ).fetchone()[0]
        r["pending_count"] = pending
        conns.append(r)
    return conns


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM plaid_connections WHERE id=?", (connection_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Connection not found")
    db.execute("DELETE FROM plaid_connections WHERE id=?", (connection_id,))
    db.commit()


@router.post("/sync")
def sync_transactions(
    connection_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
):
    """Pull new transactions from Plaid and stage them for review."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest

    client   = _plaid_client()
    accounts = [dict(r) for r in db.execute("SELECT id, code, name, type FROM accounts").fetchall()]

    if connection_id:
        connections = db.execute("SELECT * FROM plaid_connections WHERE id=?", (connection_id,)).fetchall()
    else:
        connections = db.execute("SELECT * FROM plaid_connections").fetchall()

    if not connections:
        raise HTTPException(400, "No bank connections found — connect a bank account first")

    total_added = 0
    for conn in [dict(c) for c in connections]:
        cursor   = conn.get("cursor") or None
        has_more = True

        while has_more:
            kwargs = {"access_token": conn["access_token"]}
            if cursor:
                kwargs["cursor"] = cursor
            resp = client.transactions_sync(TransactionsSyncRequest(**kwargs))

            for tx in resp.added:
                if db.execute("SELECT id FROM plaid_pending WHERE plaid_transaction_id=?",
                              (tx.transaction_id,)).fetchone():
                    continue  # already staged

                s = _suggest(tx.name or "", getattr(tx, "merchant_name", "") or "", tx.amount, accounts)
                category_json = None
                if hasattr(tx, "personal_finance_category") and tx.personal_finance_category:
                    try:
                        category_json = json.dumps(tx.personal_finance_category.to_dict())
                    except Exception:
                        pass

                db.execute(
                    """INSERT INTO plaid_pending
                       (plaid_transaction_id, plaid_account_id, connection_id, date, description,
                        merchant_name, amount, plaid_category,
                        suggested_account_id, suggested_dba, suggested_confidence)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (tx.transaction_id, tx.account_id, conn["id"],
                     str(tx.date), tx.name,
                     getattr(tx, "merchant_name", None),
                     tx.amount, category_json,
                     s["account_id"], s["dba"], s["confidence"]),
                )
                total_added += 1

            cursor   = resp.next_cursor
            has_more = resp.has_more

        db.execute(
            "UPDATE plaid_connections SET cursor=?, last_synced=datetime('now','localtime') WHERE id=?",
            (cursor, conn["id"]),
        )

    db.commit()
    return {"added_to_queue": total_added}


@router.get("/pending")
def get_pending(
    status: str = "pending",
    limit: int = 100,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
):
    rows = db.execute(
        """SELECT pp.*, a.code AS suggested_account_code, a.name AS suggested_account_name,
                  c.institution_name
           FROM plaid_pending pp
           LEFT JOIN accounts a ON a.id = pp.suggested_account_id
           LEFT JOIN plaid_connections c ON c.id = pp.connection_id
           WHERE pp.status = ?
           ORDER BY pp.date DESC, pp.id DESC
           LIMIT ? OFFSET ?""",
        (status, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


class PostBody(BaseModel):
    account_id: int
    dba: str
    description: Optional[str] = None


@router.post("/post/{pending_id}")
def post_transaction(
    pending_id: int,
    body: PostBody,
    db: sqlite3.Connection = Depends(get_db),
):
    """Approve a staged transaction and write it as a double-entry journal entry."""
    pend = db.execute("SELECT * FROM plaid_pending WHERE id=?", (pending_id,)).fetchone()
    if not pend:
        raise HTTPException(404, "Pending transaction not found")
    pend = dict(pend)
    if pend["status"] != "pending":
        raise HTTPException(400, f"Transaction already {pend['status']}")

    # Resolve the checking/bank account linked to the Plaid account
    linked = db.execute(
        "SELECT kb_account_id FROM plaid_accounts WHERE plaid_account_id=?",
        (pend["plaid_account_id"],),
    ).fetchone()
    bank_id = (linked["kb_account_id"] if linked and linked["kb_account_id"]
               else db.execute("SELECT id FROM accounts WHERE code='1000'").fetchone()["id"])

    amount = abs(pend["amount"])

    # Plaid positive = money OUT (expense).  Plaid negative = money IN (income).
    if pend["amount"] > 0:
        lines = [
            {"account_id": body.account_id, "debit": amount, "credit": 0.0},
            {"account_id": bank_id,         "debit": 0.0,    "credit": amount},
        ]
    else:
        lines = [
            {"account_id": bank_id,         "debit": amount, "credit": 0.0},
            {"account_id": body.account_id, "debit": 0.0,    "credit": amount},
        ]

    desc = body.description or pend["description"]
    cur  = db.execute(
        "INSERT INTO journal_entries (date, description, dba, memo) VALUES (?,?,?,?)",
        (pend["date"], desc, body.dba, f"Plaid:{pend['plaid_transaction_id']}"),
    )
    entry_id = cur.lastrowid

    for ln in lines:
        db.execute(
            "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (?,?,?,?)",
            (entry_id, ln["account_id"], ln["debit"], ln["credit"]),
        )

    db.execute(
        "UPDATE plaid_pending SET status='posted', journal_entry_id=? WHERE id=?",
        (entry_id, pending_id),
    )
    db.commit()
    return {"journal_entry_id": entry_id}


@router.post("/skip/{pending_id}", status_code=204)
def skip_transaction(pending_id: int, db: sqlite3.Connection = Depends(get_db)):
    pend = db.execute("SELECT id FROM plaid_pending WHERE id=?", (pending_id,)).fetchone()
    if not pend:
        raise HTTPException(404, "Pending transaction not found")
    db.execute("UPDATE plaid_pending SET status='skipped' WHERE id=?", (pending_id,))
    db.commit()


class SuggestBody(BaseModel):
    use_ai: bool = True
    use_claude: Optional[bool] = None


@router.post("/suggest/{pending_id}")
async def re_suggest(
    pending_id: int,
    body: SuggestBody,
    db: sqlite3.Connection = Depends(get_db),
):
    """Re-run categorization on a pending transaction (optionally asking AI)."""
    pend = db.execute("SELECT * FROM plaid_pending WHERE id=?", (pending_id,)).fetchone()
    if not pend:
        raise HTTPException(404, "Pending transaction not found")
    pend = dict(pend)
    accounts = [dict(r) for r in db.execute("SELECT id, code, name, type FROM accounts").fetchall()]

    use_ai = body.use_ai if body.use_claude is None else body.use_claude
    if use_ai:
        s = await _ai_suggest(pend["description"], pend.get("merchant_name") or "",
                              pend["amount"], accounts, db)
    else:
        s = _suggest(pend["description"], pend.get("merchant_name") or "", pend["amount"], accounts)

    db.execute(
        "UPDATE plaid_pending SET suggested_account_id=?, suggested_dba=?, suggested_confidence=? WHERE id=?",
        (s["account_id"], s["dba"], s["confidence"], pending_id),
    )
    db.commit()
    return {**s, "reason": s.get("reason", "")}


@router.post("/link-accounts/{connection_id}")
def link_plaid_account(
    connection_id: int,
    plaid_account_id: str,
    kb_account_id: int,
    db: sqlite3.Connection = Depends(get_db),
):
    """Map a Plaid bank account to a chart-of-accounts entry (e.g., Plaid checking → 1000)."""
    db.execute(
        "UPDATE plaid_accounts SET kb_account_id=? WHERE plaid_account_id=? AND connection_id=?",
        (kb_account_id, plaid_account_id, connection_id),
    )
    db.commit()
    return {"linked": True}


@router.get("/plaid-accounts/{connection_id}")
def get_plaid_accounts(connection_id: int, db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT pa.*, a.code AS kb_code, a.name AS kb_name
           FROM plaid_accounts pa
           LEFT JOIN accounts a ON a.id = pa.kb_account_id
           WHERE pa.connection_id = ?""",
        (connection_id,),
    ).fetchall()
    return [dict(r) for r in rows]
