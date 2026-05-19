from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
import sqlite3
import csv
import io
from datetime import datetime

from ..database import get_db

router = APIRouter(prefix="/api/import", tags=["import"])


def _parse_patriot_csv(content: str) -> list[dict]:
    """Parse Patriot GL export CSV.

    Expected columns (flexible): Date, Description, Debit, Credit, Account, Reference
    Also handles simple bank export: Date, Description, Amount
    """
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for i, row in enumerate(reader):
        # Normalize column names
        normalized = {k.strip().lower(): v.strip() for k, v in row.items()}
        rows.append({"row_num": i + 2, "data": normalized, "raw": str(row)})
    return rows


def _detect_columns(sample_rows: list[dict]) -> dict:
    """Return column mapping guess from sample rows."""
    if not sample_rows:
        return {}
    keys = list(sample_rows[0]["data"].keys())
    mapping = {}
    for key in keys:
        kl = key.lower()
        if "date" in kl:
            mapping["date"] = key
        elif "desc" in kl or "memo" in kl or "narr" in kl:
            mapping["description"] = key
        elif "debit" in kl:
            mapping["debit"] = key
        elif "credit" in kl:
            mapping["credit"] = key
        elif "amount" in kl or "amt" in kl:
            mapping["amount"] = key
        elif "ref" in kl:
            mapping["reference"] = key
        elif "account" in kl or "acct" in kl:
            mapping["account"] = key
    return mapping


@router.post("/csv")
async def import_csv(
    file:    UploadFile = File(...),
    dba:     str = "shared",
    account_id: int = None,
    db:      sqlite3.Connection = Depends(get_db),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    content = (await file.read()).decode("utf-8-sig", errors="replace")
    rows = _parse_patriot_csv(content)
    if not rows:
        raise HTTPException(400, "CSV file is empty or has no data rows")

    mapping = _detect_columns(rows)
    imported = 0
    errors = []

    for r in rows:
        d = r["data"]
        try:
            raw_date = d.get(mapping.get("date", ""), "").strip()
            # Try multiple date formats
            parsed_date = None
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
                try:
                    parsed_date = datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            if not parsed_date:
                errors.append(f"Row {r['row_num']}: unparseable date '{raw_date}'")
                continue

            desc = d.get(mapping.get("description", ""), "").strip() or "Imported transaction"

            # Amount: prefer explicit debit/credit columns, fallback to amount
            amount = 0.0
            if "debit" in mapping and "credit" in mapping:
                debit_str  = d.get(mapping["debit"],  "0").replace(",", "").replace("$", "").strip() or "0"
                credit_str = d.get(mapping["credit"], "0").replace(",", "").replace("$", "").strip() or "0"
                amount = float(debit_str) - float(credit_str)
            elif "amount" in mapping:
                amt_str = d.get(mapping["amount"], "0").replace(",", "").replace("$", "").strip() or "0"
                amount = float(amt_str)

            db.execute(
                """INSERT INTO transactions (date, description, amount, account_id, source, raw_csv_row)
                   VALUES (?,?,?,?,?,?)""",
                (parsed_date, desc, round(amount, 2), account_id, "import", r["raw"]),
            )
            imported += 1
        except Exception as exc:
            errors.append(f"Row {r['row_num']}: {exc}")

    db.commit()
    return {
        "imported": imported,
        "skipped":  len(errors),
        "errors":   errors[:20],
        "column_mapping": mapping,
    }


@router.post("/csv/preview")
async def preview_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    rows = _parse_patriot_csv(content)
    mapping = _detect_columns(rows)
    return {
        "total_rows": len(rows),
        "column_mapping": mapping,
        "preview": [r["data"] for r in rows[:10]],
        "columns": list(rows[0]["data"].keys()) if rows else [],
    }
