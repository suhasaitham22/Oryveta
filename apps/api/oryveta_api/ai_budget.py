"""Durable, per-account daily AI token reservations (SQLite single-host)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from .database import Database

DAILY_TOKEN_LIMIT = 20_000
MAX_IN_FLIGHT = 2
RESERVATION_TTL_SECONDS = 120


class BudgetExceeded(ValueError):
    """Daily token budget or concurrent model-call capacity is exhausted."""


class AiBudget:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def utc_day(now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()

    def reserve(self, user_id: str, tokens: int) -> str:
        if not 1 <= tokens <= DAILY_TOKEN_LIMIT:
            raise BudgetExceeded("Request exceeds the daily AI token budget")
        now = time.time()
        day = self.utc_day(now)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # A crashed worker may have consumed tokens. Expiry charges its
            # entire reservation, rather than silently refunding unknown usage.
            conn.execute("""UPDATE ai_calls SET status='expired',charged_tokens=reserved_tokens,
                updated_at=? WHERE status='reserved' AND expires_at<=?""", (now, now))
            rows = conn.execute("""SELECT status,reserved_tokens,charged_tokens FROM ai_calls
                WHERE user_id=? AND day_utc=?""", (user_id, day)).fetchall()
            in_flight = sum(row["status"] == "reserved" for row in rows)
            spent = sum(row["reserved_tokens"] if row["status"] == "reserved"
                        else row["charged_tokens"] for row in rows)
            if in_flight >= MAX_IN_FLIGHT or spent + tokens > DAILY_TOKEN_LIMIT:
                raise BudgetExceeded("AI token budget or concurrency limit reached")
            call_id = self.db.new_id()
            conn.execute("""INSERT INTO ai_calls
                (id,user_id,day_utc,status,reserved_tokens,charged_tokens,expires_at,
                 created_at,updated_at) VALUES(?,?,?,'reserved',?,0,?,?,?)""",
                (call_id, user_id, day, tokens, now + RESERVATION_TTL_SECONDS, now, now))
            conn.commit()
        return call_id

    def settle(self, user_id: str, call_id: str, actual_tokens: int | None) -> bool:
        """Charge actual verified usage; unknown usage is charged in full.

        A late result after reservation expiry cannot refund or overwrite a
        terminal record. Returns False when no active reservation remains.
        """
        now = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT reserved_tokens,expires_at FROM ai_calls
                WHERE id=? AND user_id=? AND status='reserved'""",
                (call_id, user_id)).fetchone()
            if row is None:
                conn.commit()
                return False
            expired = now >= row["expires_at"]
            if actual_tokens is None or expired:
                charge = row["reserved_tokens"]
            elif type(actual_tokens) is not int or actual_tokens < 0:
                charge = row["reserved_tokens"]
            else:
                # Charge even if a provider violates the predeclared bound;
                # the API independently rejects the over-budget response.
                charge = actual_tokens
            conn.execute("""UPDATE ai_calls SET status=?,charged_tokens=?,updated_at=?
                WHERE id=? AND user_id=? AND status='reserved'""",
                ("expired" if expired else "completed" if actual_tokens is not None
                 else "failed", charge, now, call_id, user_id))
            conn.commit()
        return not expired

    def summary(self, user_id: str) -> dict:
        now = time.time()
        day = self.utc_day(now)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""UPDATE ai_calls SET status='expired',charged_tokens=reserved_tokens,
                updated_at=? WHERE status='reserved' AND expires_at<=?""", (now, now))
            rows = conn.execute("""SELECT status,reserved_tokens,charged_tokens FROM ai_calls
                WHERE user_id=? AND day_utc=?""", (user_id, day)).fetchall()
            conn.commit()
        used = sum(row["reserved_tokens"] if row["status"] == "reserved"
                   else row["charged_tokens"] for row in rows)
        return {"day_utc": day, "limit_tokens": DAILY_TOKEN_LIMIT,
                "allocated_tokens": used, "remaining_tokens": max(0, DAILY_TOKEN_LIMIT - used),
                "active_calls": sum(row["status"] == "reserved" for row in rows)}
