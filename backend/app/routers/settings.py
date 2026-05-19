from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import sqlite3

from ..database import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingWrite(BaseModel):
    value: str


@router.get("/{key}")
def get_setting(key: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return {"key": key, "value": row["value"] if row else None}


@router.post("/{key}")
def set_setting(key: str, body: SettingWrite, db: sqlite3.Connection = Depends(get_db)):
    db.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime'))
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, body.value),
    )
    db.commit()
    return {"key": key, "value": body.value, "saved": True}


@router.delete("/{key}", status_code=204)
def delete_setting(key: str, db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM settings WHERE key = ?", (key,))
    db.commit()
