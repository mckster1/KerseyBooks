from fastapi import APIRouter, Depends, HTTPException
import sqlite3

from ..database import get_db
from ..llm import complete_text, get_llm_config
from ..models import AskRequest, AskResponse

router = APIRouter(prefix="/api/ask", tags=["ask"])


def _build_context(db: sqlite3.Connection, start: str, end: str, dba: str) -> str:
    """Build a financial summary to include in the AI prompt."""
    dba_clause = ""
    dba_params: list = []
    if dba and dba != "all":
        dba_clause = " AND (je.dba = ? OR je.dba = 'both')"
        dba_params = [dba]

    rows = db.execute(
        f"""SELECT a.code, a.name, a.type,
                   COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.debit ELSE 0 END), 0) AS total_debit,
                   COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.credit ELSE 0 END), 0) AS total_credit
            FROM accounts a
            LEFT JOIN journal_lines jl  ON jl.account_id = a.id
            LEFT JOIN journal_entries je ON je.id = jl.journal_entry_id
                AND je.date BETWEEN ? AND ?{dba_clause}
            WHERE a.active = 1
            GROUP BY a.id
            ORDER BY a.code""",
        [start, end] + dba_params,
    ).fetchall()

    lines = [f"Financial data for period {start} to {end} (DBA filter: {dba}):"]
    lines.append("")
    lines.append("Account Code | Account Name | Type | Net Activity")
    lines.append("-------------|--------------|------|-------------")
    for row in rows:
        if row["type"] == "income":
            net = row["total_credit"] - row["total_debit"]
        elif row["type"] == "expense":
            net = row["total_debit"] - row["total_credit"]
        else:
            net = row["total_debit"] - row["total_credit"]
        if abs(net) > 0.005:
            lines.append(f"{row['code']} | {row['name']} | {row['type']} | ${net:,.2f}")
    return "\n".join(lines)


@router.post("", response_model=AskResponse)
def ask_assistant(body: AskRequest, db: sqlite3.Connection = Depends(get_db)):
    start = body.start_date or "2024-01-01"
    end = body.end_date or "2099-12-31"
    context = _build_context(db, start, end, body.dba or "all")
    config = get_llm_config(db, body.provider, body.model)

    system_prompt = (
        "You are an expert small-business bookkeeper assistant for Kersey Car Wash and "
        "Kersey Laundromat, two DBAs of the same owner. You have access to their "
        "QuickBooks-style general ledger data. Answer questions clearly and concisely "
        "in plain English. When providing dollar amounts, format them with commas and "
        "two decimal places. If you're uncertain, say so - accuracy matters for tax purposes."
    )
    user_message = f"{context}\n\nQuestion: {body.question}"

    try:
        answer = complete_text(config, system_prompt, user_message, max_tokens=1024)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"AI provider request failed: {exc}")

    return AskResponse(
        answer=answer,
        context_used=context[:500] + "..." if len(context) > 500 else context,
    )
