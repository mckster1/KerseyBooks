from datetime import datetime
from pathlib import Path
import json
import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..database import DB_PATH, get_db

router = APIRouter(prefix="/api/google-drive", tags=["google-drive"])

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _setting(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"]:
        return row["value"]
    return None


def _save_setting(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime'))
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, value),
    )
    db.commit()


def _client_config(db: sqlite3.Connection) -> dict:
    client_id = _setting(db, "google_client_id") or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = _setting(db, "google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(
            503,
            "Google Drive OAuth is not configured. Add Google client ID and secret in Settings.",
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _redirect_uri(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/api/google-drive/callback"


def _load_credentials(db: sqlite3.Connection):
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2.credentials import Credentials
    except ImportError:
        raise HTTPException(503, "Google API packages are not installed")

    token_json = _setting(db, "google_drive_token")
    if not token_json:
        raise HTTPException(401, "Google Drive is not connected")

    credentials = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
        _save_setting(db, "google_drive_token", credentials.to_json())
    if not credentials.valid:
        raise HTTPException(401, "Google Drive connection expired. Reconnect Google Drive.")
    return credentials


def _drive_service(db: sqlite3.Connection):
    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise HTTPException(503, "Google API packages are not installed")

    return build("drive", "v3", credentials=_load_credentials(db), cache_discovery=False)


def _checkpoint_database() -> None:
    if not Path(DB_PATH).exists():
        raise HTTPException(404, "Database file not found")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


@router.get("/status")
def drive_status(db: sqlite3.Connection = Depends(get_db)):
    configured = bool(
        (_setting(db, "google_client_id") or os.getenv("GOOGLE_CLIENT_ID"))
        and (_setting(db, "google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET"))
    )
    connected = bool(_setting(db, "google_drive_token"))
    email = None
    if connected:
        try:
            about = _drive_service(db).about().get(fields="user(emailAddress)").execute()
            email = about.get("user", {}).get("emailAddress")
        except Exception:
            connected = False
    return {
        "configured": configured,
        "connected": connected,
        "email": email,
        "folder_id": _setting(db, "google_drive_folder_id") or os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""),
        "backup_file_id": _setting(db, "google_drive_backup_file_id"),
    }


@router.get("/auth-url")
def auth_url(request: Request, db: sqlite3.Connection = Depends(get_db)):
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise HTTPException(503, "Google API packages are not installed")

    flow = Flow.from_client_config(
        _client_config(db),
        scopes=SCOPES,
        redirect_uri=_redirect_uri(request),
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"auth_url": url, "redirect_uri": _redirect_uri(request)}


@router.get("/callback")
def oauth_callback(
    request: Request,
    code: str,
    db: sqlite3.Connection = Depends(get_db),
):
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise HTTPException(503, "Google API packages are not installed")

    flow = Flow.from_client_config(
        _client_config(db),
        scopes=SCOPES,
        redirect_uri=_redirect_uri(request),
    )
    flow.fetch_token(code=code)
    _save_setting(db, "google_drive_token", flow.credentials.to_json())
    return HTMLResponse(
        "<!doctype html><title>KerseyBooks</title>"
        "<p>Google Drive connected. You can close this tab and return to KerseyBooks.</p>"
    )


@router.delete("/connection", status_code=204)
def disconnect_drive(db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM settings WHERE key IN ('google_drive_token', 'google_drive_backup_file_id')")
    db.commit()


@router.post("/backup")
def upload_backup(db: sqlite3.Connection = Depends(get_db)):
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        raise HTTPException(503, "Google API packages are not installed")

    _checkpoint_database()
    service = _drive_service(db)
    folder_id = _setting(db, "google_drive_folder_id") or os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    backup_file_id = _setting(db, "google_drive_backup_file_id")
    media = MediaFileUpload(DB_PATH, mimetype="application/x-sqlite3", resumable=False)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if backup_file_id:
        try:
            result = service.files().update(
                fileId=backup_file_id,
                media_body=media,
                fields="id,name,webViewLink,modifiedTime",
            ).execute()
        except Exception:
            backup_file_id = None

    if not backup_file_id:
        metadata = {
            "name": "kersey_backup.db",
            "description": f"KerseyBooks database backup uploaded {timestamp}",
        }
        if folder_id:
            metadata["parents"] = [folder_id]
        result = service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,webViewLink,modifiedTime",
        ).execute()
        _save_setting(db, "google_drive_backup_file_id", result["id"])

    return {
        "uploaded": True,
        "file_id": result["id"],
        "name": result.get("name"),
        "url": result.get("webViewLink"),
        "modified_time": result.get("modifiedTime"),
    }
