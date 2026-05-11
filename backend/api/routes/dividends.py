"""Dividend management routes for account and dividend history."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from zoneinfo import ZoneInfo

from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/dividends", tags=["Dividends"])


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class DividendAccountCreate(BaseModel):
    owner_name: str
    account_number: str
    bank_name: str

class BulkDeleteIds(BaseModel):
    ids: list[str]

class DividendEntryCreate(BaseModel):
    account_id: str
    dividend_date: str
    amount: float
    tax: float
    net_amount: float
    memo: str = ""


# ─── Helper Functions ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


# ─── Routes: Accounts ────────────────────────────────────────────────────────

@router.post("/accounts")
async def create_dividend_account(payload: DividendAccountCreate):
    """Register a new dividend account."""
    account_id = str(uuid.uuid4())
    now = _now_iso()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO dividend_accounts (id, owner_name, account_number, bank_name, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (account_id, payload.owner_name, payload.account_number, payload.bank_name, now, now),
            )
        return {"ok": True, "account_id": account_id}
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=400, detail="Account number already registered.")
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/accounts")
async def list_dividend_accounts():
    """Return all active dividend accounts."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM dividend_accounts WHERE is_active = 1 ORDER BY bank_name ASC").fetchall()
    return {"ok": True, "accounts": [dict(row) for row in rows]}

@router.put("/accounts/{account_id}")
async def update_dividend_account(account_id: str, payload: DividendAccountCreate):
    """Update an existing dividend account."""
    now = _now_iso()
    with get_connection() as conn:
        res = conn.execute(
            """
            UPDATE dividend_accounts 
            SET owner_name = ?, account_number = ?, bank_name = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.owner_name, payload.account_number, payload.bank_name, now, account_id),
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found.")
    return {"ok": True}

@router.delete("/accounts/{account_id}")
async def delete_dividend_account(account_id: str):
    """Delete a dividend account (soft delete by setting is_active=0)."""
    with get_connection() as conn:
        res = conn.execute("UPDATE dividend_accounts SET is_active = 0 WHERE id = ?", (account_id,))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found.")
    return {"ok": True}

@router.post("/accounts/bulk-delete")
async def bulk_delete_dividend_accounts(payload: BulkDeleteIds):
    """Soft delete multiple accounts at once."""
    if not payload.ids:
        return {"ok": True, "count": 0}
    
    placeholders = ",".join(["?"] * len(payload.ids))
    with get_connection() as conn:
        res = conn.execute(
            f"UPDATE dividend_accounts SET is_active = 0 WHERE id IN ({placeholders})",
            payload.ids
        )
    return {"ok": True, "count": res.rowcount}


# ─── Routes: Dividends ───────────────────────────────────────────────────────

@router.post("/entries")
async def create_dividend_entry(payload: DividendEntryCreate):
    """Add a new dividend record."""
    entry_id = str(uuid.uuid4())
    now = _now_iso()
    with get_connection() as conn:
        # Check if account exists
        acc = conn.execute("SELECT id FROM dividend_accounts WHERE id = ?", (payload.account_id,)).fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found.")
        
        conn.execute(
            """
            INSERT INTO dividends (id, account_id, dividend_date, amount, tax, net_amount, memo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_id, payload.account_id, payload.dividend_date, payload.amount, payload.tax, payload.net_amount, payload.memo, now, now),
        )
    return {"ok": True, "entry_id": entry_id}

@router.get("/history")
async def list_dividend_history(account_id: str | None = None, start_date: str | None = None, end_date: str | None = None):
    """Return dividend history with optional filters."""
    query = """
        SELECT d.*, a.bank_name, a.account_number, a.owner_name
        FROM dividends d
        JOIN dividend_accounts a ON d.account_id = a.id
        WHERE 1=1
    """
    params = []
    if account_id:
        query += " AND d.account_id = ?"
        params.append(account_id)
    if start_date:
        query += " AND d.dividend_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND d.dividend_date <= ?"
        params.append(end_date)
    
    query += " ORDER BY d.dividend_date DESC, d.created_at DESC"
    
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return {"ok": True, "history": [dict(row) for row in rows]}

@router.put("/entries/{entry_id}")
async def update_dividend_entry(entry_id: str, payload: DividendEntryCreate):
    """Update an existing dividend entry."""
    now = _now_iso()
    with get_connection() as conn:
        res = conn.execute(
            """
            UPDATE dividends 
            SET account_id = ?, dividend_date = ?, amount = ?, tax = ?, net_amount = ?, memo = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.account_id, payload.dividend_date, payload.amount, payload.tax, payload.net_amount, payload.memo, now, entry_id),
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entry not found.")
    return {"ok": True}

@router.delete("/entries/{entry_id}")
async def delete_dividend_entry(entry_id: str):
    """Delete a dividend entry."""
    with get_connection() as conn:
        res = conn.execute("DELETE FROM dividends WHERE id = ?", (entry_id,))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entry not found.")
    return {"ok": True}

@router.post("/entries/bulk-delete")
async def bulk_delete_dividend_entries(payload: BulkDeleteIds):
    """Delete multiple dividend entries at once."""
    if not payload.ids:
        return {"ok": True, "count": 0}
    
    placeholders = ",".join(["?"] * len(payload.ids))
    with get_connection() as conn:
        res = conn.execute(
            f"DELETE FROM dividends WHERE id IN ({placeholders})",
            payload.ids
        )
    return {"ok": True, "count": res.rowcount}


# ─── Routes: Stats ───────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def get_dividend_stats(year: int | None = None):
    """Return dividend statistics grouped by month and account."""
    target_year = year or datetime.now(ZoneInfo("Asia/Seoul")).year
    date_prefix = f"{target_year}-%"
    
    with get_connection() as conn:
        # Monthly breakdown
        monthly_rows = conn.execute(
            """
            SELECT strftime('%m', dividend_date) as month, SUM(net_amount) as total_net
            FROM dividends
            WHERE dividend_date LIKE ?
            GROUP BY month
            ORDER BY month ASC
            """,
            (date_prefix,),
        ).fetchall()
        
        # Account breakdown
        account_rows = conn.execute(
            """
            SELECT a.bank_name, a.account_number, SUM(d.net_amount) as total_net
            FROM dividends d
            JOIN dividend_accounts a ON d.account_id = a.id
            WHERE d.dividend_date LIKE ?
            GROUP BY a.id
            ORDER BY total_net DESC
            """,
            (date_prefix,),
        ).fetchall()
        
        # Total
        total_row = conn.execute(
            "SELECT SUM(amount) as gross, SUM(tax) as tax, SUM(net_amount) as net FROM dividends WHERE dividend_date LIKE ?",
            (date_prefix,),
        ).fetchone()

    return {
        "ok": True,
        "year": target_year,
        "total": dict(total_row) if total_row["gross"] is not None else {"gross": 0, "tax": 0, "net": 0},
        "monthly": [dict(row) for row in monthly_rows],
        "by_account": [dict(row) for row in account_rows]
    }
