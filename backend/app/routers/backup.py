from datetime import datetime
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..database import DB_PATH, get_db

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _setting(db: sqlite3.Connection, key: str) -> str:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def _checkpoint_db() -> None:
    source = sqlite3.connect(DB_PATH)
    try:
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source.close()


def _write_sqlite_backup(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(DB_PATH)
    try:
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


@router.get("")
def download_backup():
    if not Path(DB_PATH).exists():
        raise HTTPException(404, "Database file not found")
    _checkpoint_db()
    return FileResponse(
        path=DB_PATH,
        filename="kersey_backup.db",
        media_type="application/octet-stream",
    )


@router.get("/folder/status")
def backup_folder_status(db: sqlite3.Connection = Depends(get_db)):
    folder_path = _setting(db, "backup_folder_path")
    exists = bool(folder_path) and Path(folder_path).expanduser().exists()
    return {
        "configured": bool(folder_path),
        "folder_path": folder_path,
        "exists": exists,
    }


@router.post("/folder")
def copy_backup_to_folder(db: sqlite3.Connection = Depends(get_db)):
    folder_path = _setting(db, "backup_folder_path").strip()
    if not folder_path:
        raise HTTPException(400, "Choose a backup folder first.")

    folder = Path(folder_path).expanduser()
    if folder.exists() and not folder.is_dir():
        raise HTTPException(400, "Backup location must be a folder, not a file.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = folder / f"kersey_backup_{timestamp}.db"
    counter = 2
    while backup_path.exists():
        backup_path = folder / f"kersey_backup_{timestamp}_{counter}.db"
        counter += 1
    try:
        _write_sqlite_backup(backup_path)
    except OSError as exc:
        raise HTTPException(400, f"Could not write to that backup folder: {exc}") from exc

    return {
        "saved": True,
        "folder_path": str(folder),
        "file_path": str(backup_path),
        "name": backup_path.name,
    }
