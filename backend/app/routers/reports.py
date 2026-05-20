from fastapi import APIRouter, Depends, Query
from typing import Optional
import sqlite3
from datetime import date, timedelta
import calendar

from ..database import get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _dba_filter(dba: Optional[str]) -> tuple:
    """Return (sql_fragment, params) for DBA filtering on journal_entries je."""
    if not dba or dba == "all":
        return "", []
    return " AND (je.dba = ? OR je.dba = 'both')", [dba]


def _pl_query(db: sqlite3.Connection, start: str, end: str, dba: Optional[str]):
    dba_sql, dba_params = _dba_filter(dba)
    rows = db.execute(
        f"""SELECT a.id, a.code, a.name, a.type,
                   COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.debit ELSE 0 END), 0) AS total_debit,
                   COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.credit ELSE 0 END), 0) AS total_credit
            FROM accounts a
            LEFT JOIN journal_lines jl  ON jl.account_id = a.id
            LEFT JOIN journal_entries je ON je.id = jl.journal_entry_id
                AND je.date BETWEEN ? AND ?{dba_sql}
            WHERE a.type IN ('income','expense')
            GROUP BY a.id, a.code, a.name, a.type
            ORDER BY a.code""",
        [start, end] + dba_params,
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/pl")
def profit_and_loss(
    start: str = Query(...),
    end:   str = Query(...),
    dba:   Optional[str] = Query("all"),
    db:    sqlite3.Connection = Depends(get_db),
):
    rows = _pl_query(db, start, end, dba)
    income_items, expense_items = [], []
    total_income = total_expenses = 0.0

    for r in rows:
        if r["type"] == "income":
            net = round(r["total_credit"] - r["total_debit"], 2)
            income_items.append({**r, "net": net})
            total_income += net
        else:
            net = round(r["total_debit"] - r["total_credit"], 2)
            expense_items.append({**r, "net": net})
            total_expenses += net

    return {
        "start": start,
        "end": end,
        "dba": dba,
        "income": income_items,
        "expenses": expense_items,
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "net_income": round(total_income - total_expenses, 2),
    }


@router.get("/balance-sheet")
def balance_sheet(
    as_of: str = Query(...),
    dba:   Optional[str] = Query("all"),
    db:    sqlite3.Connection = Depends(get_db),
):
    dba_sql, dba_params = _dba_filter(dba)
    rows = db.execute(
        f"""SELECT a.id, a.code, a.name, a.type, a.normal_balance,
                   COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.debit ELSE 0 END), 0) AS total_debit,
                   COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.credit ELSE 0 END), 0) AS total_credit
            FROM accounts a
            LEFT JOIN journal_lines jl  ON jl.account_id = a.id
            LEFT JOIN journal_entries je ON je.id = jl.journal_entry_id
                AND je.date <= ?{dba_sql}
            WHERE a.type IN ('asset','liability','equity')
            GROUP BY a.id, a.code, a.name, a.type, a.normal_balance
            ORDER BY a.code""",
        [as_of] + dba_params,
    ).fetchall()

    assets, liabilities, equity = [], [], []
    total_assets = total_liabilities = total_equity = 0.0

    for r in rows:
        r = dict(r)
        if r["normal_balance"] == "debit":
            balance = round(r["total_debit"] - r["total_credit"], 2)
        else:
            balance = round(r["total_credit"] - r["total_debit"], 2)
        r["balance"] = balance

        if r["type"] == "asset":
            assets.append(r);      total_assets      += balance
        elif r["type"] == "liability":
            liabilities.append(r); total_liabilities += balance
        else:
            equity.append(r);      total_equity      += balance

    # Include current-year net income in equity so the balance sheet balances mid-period
    # (income/expense accounts close to retained earnings at year-end)
    cy_pl = _pl_query(db, f"{as_of[:4]}-01-01", as_of, dba)
    cy_income   = sum(r["total_credit"] - r["total_debit"] for r in cy_pl if r["type"] == "income")
    cy_expenses = sum(r["total_debit"] - r["total_credit"] for r in cy_pl if r["type"] == "expense")
    cy_net = round(cy_income - cy_expenses, 2)
    if cy_net != 0:
        equity.append({
            "id": None, "code": "3099", "name": "Current Year Net Income",
            "type": "equity", "normal_balance": "credit",
            "total_debit": 0, "total_credit": 0, "balance": cy_net,
        })
        total_equity += cy_net

    return {
        "as_of": as_of,
        "dba": dba,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets": round(total_assets, 2),
        "total_liabilities": round(total_liabilities, 2),
        "total_equity": round(total_equity, 2),
        "is_balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.02,
    }


@router.get("/cash-flow")
def cash_flow(
    start: str = Query(...),
    end:   str = Query(...),
    dba:   Optional[str] = Query("all"),
    db:    sqlite3.Connection = Depends(get_db),
):
    dba_sql, dba_params = _dba_filter(dba)

    def account_balance(code: str, as_of: str) -> float:
        row = db.execute(
            f"""SELECT COALESCE(SUM(jl.debit),0)-COALESCE(SUM(jl.credit),0) AS bal
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id{dba_sql if dba_params else ''}
                JOIN accounts a ON a.id = jl.account_id
                WHERE a.code = ? AND je.date <= ?""",
            (dba_params + [code, as_of]) if dba_params else [code, as_of],
        ).fetchone()
        return round(row[0] or 0.0, 2)

    # Day before start for beginning balance
    start_date = date.fromisoformat(start)
    day_before = (start_date - timedelta(days=1)).isoformat()

    begin_cash = account_balance("1000", day_before)
    end_cash   = account_balance("1000", end)

    # Operating cash: net income for period
    pl = _pl_query(db, start, end, dba)
    net_income = 0.0
    for r in pl:
        if r["type"] == "income":
            net_income += r["total_credit"] - r["total_debit"]
        else:
            net_income -= r["total_debit"] - r["total_credit"]

    # Cash transactions against checking account
    cash_rows = db.execute(
        f"""SELECT je.date, je.description, je.dba, jl.debit, jl.credit
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE a.code = '1000' AND je.date BETWEEN ? AND ?{dba_sql}
            ORDER BY je.date, je.id""",
        [start, end] + dba_params,
    ).fetchall()

    return {
        "start": start,
        "end": end,
        "dba": dba,
        "beginning_cash": begin_cash,
        "ending_cash": end_cash,
        "net_change": round(end_cash - begin_cash, 2),
        "net_income": round(net_income, 2),
        "cash_transactions": [dict(r) for r in cash_rows],
    }


@router.get("/expense-categories")
def expense_categories(
    start: str = Query(...),
    end:   str = Query(...),
    dba:   Optional[str] = Query("all"),
    db:    sqlite3.Connection = Depends(get_db),
):
    dba_sql, dba_params = _dba_filter(dba)
    rows = db.execute(
        f"""SELECT a.code, a.name,
                   COALESCE(SUM(jl.debit),0)-COALESCE(SUM(jl.credit),0) AS total
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE a.type = 'expense'
              AND je.date BETWEEN ? AND ?{dba_sql}
            GROUP BY a.id, a.code, a.name
            HAVING total > 0
            ORDER BY total DESC""",
        [start, end] + dba_params,
    ).fetchall()
    return {
        "start": start, "end": end, "dba": dba,
        "categories": [{"code": r["code"], "name": r["name"], "total": round(r["total"], 2)} for r in rows],
    }


@router.get("/month-over-month")
def month_over_month(
    year: int = Query(...),
    dba:  Optional[str] = Query("all"),
    db:   sqlite3.Connection = Depends(get_db),
):
    months = []
    for m in range(1, 13):
        _, last_day = calendar.monthrange(year, m)
        start = f"{year}-{m:02d}-01"
        end   = f"{year}-{m:02d}-{last_day:02d}"
        pl    = _pl_query(db, start, end, dba)
        total_income = sum(
            r["total_credit"] - r["total_debit"] for r in pl if r["type"] == "income"
        )
        total_expenses = sum(
            r["total_debit"] - r["total_credit"] for r in pl if r["type"] == "expense"
        )
        months.append({
            "month": m,
            "month_name": calendar.month_abbr[m],
            "income":   round(total_income, 2),
            "expenses": round(total_expenses, 2),
            "net":      round(total_income - total_expenses, 2),
        })
    return {"year": year, "dba": dba, "months": months}
