from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import sqlite3
from datetime import date

from ..database import get_db
from ..models import JournalEntryCreate, JournalEntryOut, JournalLineOut

router = APIRouter(prefix="/api/journal-entries", tags=["journal-entries"])


def _fetch_entry(db: sqlite3.Connection, entry_id: int) -> dict:
    entry = db.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Journal entry not found")
    lines = db.execute(
        """SELECT jl.*, a.code AS account_code, a.name AS account_name
           FROM journal_lines jl
           JOIN accounts a ON a.id = jl.account_id
           WHERE jl.journal_entry_id = ?
           ORDER BY jl.id""",
        (entry_id,),
    ).fetchall()
    result = dict(entry)
    result["lines"] = [dict(l) for l in lines]
    return result


@router.get("", response_model=List[JournalEntryOut])
def list_journal_entries(
    start:   Optional[str] = Query(None),
    end:     Optional[str] = Query(None),
    dba:     Optional[str] = Query(None),
    account: Optional[int] = Query(None),
    limit:   int = 200,
    offset:  int = 0,
    db: sqlite3.Connection = Depends(get_db),
):
    sql = "SELECT DISTINCT je.id FROM journal_entries je"
    params: list = []
    if account:
        sql += " JOIN journal_lines jl ON jl.journal_entry_id = je.id AND jl.account_id = ?"
        params.append(account)
    sql += " WHERE 1=1"
    if start:
        sql += " AND je.date >= ?"
        params.append(start)
    if end:
        sql += " AND je.date <= ?"
        params.append(end)
    if dba and dba != "all":
        sql += " AND (je.dba = ? OR je.dba = 'both')"
        params.append(dba)
    sql += " ORDER BY je.date DESC, je.id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    ids = [r[0] for r in db.execute(sql, params).fetchall()]
    return [_fetch_entry(db, i) for i in ids]


@router.get("/{entry_id}", response_model=JournalEntryOut)
def get_journal_entry(entry_id: int, db: sqlite3.Connection = Depends(get_db)):
    return _fetch_entry(db, entry_id)


@router.post("", response_model=JournalEntryOut, status_code=201)
def create_journal_entry(data: JournalEntryCreate, db: sqlite3.Connection = Depends(get_db)):
    # Validate all account_ids exist
    for line in data.lines:
        row = db.execute("SELECT id FROM accounts WHERE id = ?", (line.account_id,)).fetchone()
        if not row:
            raise HTTPException(422, f"Account id {line.account_id} does not exist")

    cur = db.execute(
        "INSERT INTO journal_entries (date, description, reference, dba, memo) VALUES (?,?,?,?,?)",
        (str(data.date), data.description, data.reference, data.dba, data.memo),
    )
    entry_id = cur.lastrowid

    for line in data.lines:
        db.execute(
            "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, dba_override) VALUES (?,?,?,?,?)",
            (entry_id, line.account_id, round(line.debit, 2), round(line.credit, 2), line.dba_override),
        )
    db.commit()
    return _fetch_entry(db, entry_id)


@router.put("/{entry_id}", response_model=JournalEntryOut)
def update_journal_entry(
    entry_id: int,
    data: JournalEntryCreate,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT id FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Journal entry not found")

    # Validate account IDs
    for line in data.lines:
        if not db.execute("SELECT id FROM accounts WHERE id = ?", (line.account_id,)).fetchone():
            raise HTTPException(422, f"Account id {line.account_id} does not exist")

    db.execute(
        """UPDATE journal_entries
           SET date=?, description=?, reference=?, dba=?, memo=?,
               updated_at=datetime('now','localtime')
           WHERE id=?""",
        (str(data.date), data.description, data.reference, data.dba, data.memo, entry_id),
    )
    db.execute("DELETE FROM journal_lines WHERE journal_entry_id = ?", (entry_id,))
    for line in data.lines:
        db.execute(
            "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, dba_override) VALUES (?,?,?,?,?)",
            (entry_id, line.account_id, round(line.debit, 2), round(line.credit, 2), line.dba_override),
        )
    db.commit()
    return _fetch_entry(db, entry_id)


@router.delete("/{entry_id}", status_code=204)
def delete_journal_entry(entry_id: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Journal entry not found")
    db.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
    db.commit()
