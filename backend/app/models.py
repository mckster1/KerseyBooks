from pydantic import BaseModel, validator, Field
from typing import Optional, List
from datetime import date, datetime


# ── Accounts ────────────────────────────────────────────────────────────────

class AccountBase(BaseModel):
    code: str
    name: str
    type: str   # asset | liability | equity | income | expense
    normal_balance: str  # debit | credit
    active: bool = True

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    normal_balance: Optional[str] = None
    active: Optional[bool] = None

class AccountOut(AccountBase):
    id: int
    class Config:
        from_attributes = True


# ── Journal Entries ──────────────────────────────────────────────────────────

class JournalLineCreate(BaseModel):
    account_id: int
    debit: float = Field(0.0, ge=0)
    credit: float = Field(0.0, ge=0)
    dba_override: Optional[str] = None

class JournalEntryCreate(BaseModel):
    date: date
    description: str
    reference: Optional[str] = None
    dba: str   # carwash | laundromat | shared | both
    memo: Optional[str] = None
    lines: List[JournalLineCreate]

    @validator("lines")
    def lines_must_balance(cls, lines):
        if len(lines) < 2:
            raise ValueError("Journal entry must have at least two lines")
        for i, l in enumerate(lines, 1):
            d, c = round(l.debit, 2), round(l.credit, 2)
            if d > 0 and c > 0:
                raise ValueError(f"Line {i}: a line cannot have both a debit and a credit amount")
            if d == 0 and c == 0:
                raise ValueError(f"Line {i}: a line must have a debit or a credit amount")
        total_debit  = sum(round(l.debit,  2) for l in lines)
        total_credit = sum(round(l.credit, 2) for l in lines)
        if abs(total_debit - total_credit) > 0.005:
            raise ValueError(
                f"Journal entry does not balance — "
                f"debits={total_debit:.2f}, credits={total_credit:.2f}"
            )
        if total_debit == 0:
            raise ValueError("Journal entry total cannot be zero")
        return lines

class JournalLineOut(BaseModel):
    id: int
    journal_entry_id: int
    account_id: int
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    debit: float
    credit: float
    dba_override: Optional[str] = None

class JournalEntryOut(BaseModel):
    id: int
    date: str
    description: str
    reference: Optional[str] = None
    dba: str
    memo: Optional[str] = None
    created_at: str
    lines: List[JournalLineOut] = []


# ── Transactions ─────────────────────────────────────────────────────────────

class TransactionOut(BaseModel):
    id: int
    date: str
    description: str
    amount: float
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    source: str
    imported_at: str


# ── Ask Claude ───────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    dba: Optional[str] = "all"

class AskResponse(BaseModel):
    answer: str
    context_used: Optional[str] = None
