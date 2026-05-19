from fastapi import APIRouter, Depends, HTTPException
import sqlite3
import os

from ..database import get_db
from ..models import AskRequest, AskResponse

router = APIRouter(prefix="/api/ask", tags=["ask"])


def _build_context(db: sqlite3.Connection, start: str, end: str, dba: str) -> str:
    """Build a financial summary to include in the Claude prompt."""
    dba_clause = ""
    dba_params: list = []
    if dba and dba != "all":
        dba_clause = " AND (je.dba = ? OR je.dba = 'both')"
        dba_params = [dba]

    rows = db.execute(
        f"""SELECT a.code, a.name, a.type,
                   COALESCE(SUM(jl.debit),0)  AS total_debit,
                   COALESCE(SUM(jl.credit),0) AS total_credit
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
    for r in rows:
        if r["type"] in ("income", "expense"):
            net = r["total_credit"] - r["total_debit"] if r["type"] == "income" else r["total_debit"] - r["total_credit"]
        else:
            net = r["total_debit"] - r["total_credit"]
        if abs(net) > 0.005:
            lines.append(f"{r['code']} | {r['name']} | {r['type']} | ${net:,.2f}")
    return "\n".join(lines)


@router.post("", response_model=AskResponse)
def ask_claude(body: AskRequest, db: sqlite3.Connection = Depends(get_db)):
    # Settings table takes priority over .env
    row = db.execute("SELECT value FROM settings WHERE key='anthropic_api_key'").fetchone()
    api_key = (row["value"] if row else None) or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured — set it in Settings")

    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "anthropic package not installed")

    start = body.start_date or "2024-01-01"
    end   = body.end_date   or "2099-12-31"
    context = _build_context(db, start, end, body.dba or "all")

    system_prompt = (
        "You are an expert small-business bookkeeper assistant for Kersey Car Wash and "
        "Kersey Laundromat, two DBAs of the same owner. You have access to their QuickBooks-style "
        "general ledger data. Answer questions clearly and concisely in plain English. "
        "When providing dollar amounts, format them with commas and two decimal places. "
        "If you're uncertain, say so — accuracy matters for tax purposes."
    )

    user_message = f"{context}\n\nQuestion: {body.question}"

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    answer = message.content[0].text

    return AskResponse(answer=answer, context_used=context[:500] + "..." if len(context) > 500 else context)
