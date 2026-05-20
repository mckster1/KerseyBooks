from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
import sqlite3

from ..database import get_db
from ..models import AccountCreate, AccountOut, AccountUpdate

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=List[AccountOut])
def list_accounts(
    type: Optional[str] = None,
    active_only: bool = False,
    db: sqlite3.Connection = Depends(get_db),
):
    sql = "SELECT * FROM accounts WHERE 1=1"
    params: list = []
    if type:
        sql += " AND type = ?"
        params.append(type)
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY code"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Account not found")
    return dict(row)


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountCreate, db: sqlite3.Connection = Depends(get_db)):
    try:
        cur = db.execute(
            "INSERT INTO accounts (code, name, type, normal_balance, active) VALUES (?,?,?,?,?)",
            (data.code, data.name, data.type, data.normal_balance, int(data.active)),
        )
        db.commit()
        row = db.execute("SELECT * FROM accounts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Account code '{data.code}' already exists")


@router.put("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    data: AccountUpdate,
    db: sqlite3.Connection = Depends(get_db),
):
    existing = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not existing:
        raise HTTPException(404, "Account not found")
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if not updates:
        return dict(existing)

    # Reclassifying an account that already has posted activity would silently
    # restate every historical report. Block it once the account is in use.
    reclassifying = (
        ("type" in updates and updates["type"] != existing["type"])
        or ("normal_balance" in updates and updates["normal_balance"] != existing["normal_balance"])
    )
    if reclassifying:
        in_use = db.execute(
            "SELECT 1 FROM journal_lines WHERE account_id = ? LIMIT 1", (account_id,)
        ).fetchone()
        if in_use:
            raise HTTPException(
                409,
                "Cannot change the type or normal balance of an account that has "
                "posted journal entries — create a new account instead.",
            )

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(
        f"UPDATE accounts SET {set_clause} WHERE id = ?",
        list(updates.values()) + [account_id],
    )
    db.commit()
    return dict(db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())
