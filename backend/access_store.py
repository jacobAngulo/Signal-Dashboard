"""Access request storage in the auth SQLite database.

The access_request table is the authorization gate: a verified Google identity
whose email has an approved row gets in; everyone else lands on
/access-requested. This replaces the old static AUTH_ALLOWED_EMAILS allowlist
with the same request-access flow industry-ops uses, wired to the ops-console
Product Ops screen.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS access_request (
  id TEXT PRIMARY KEY NOT NULL,
  email TEXT NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied')),
  decided_at INTEGER,
  decided_by TEXT,
  created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS access_request_email_idx ON access_request (email);
"""


class AccessStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(SCHEMA)
            connection.commit()
            yield connection
            connection.commit()
        finally:
            connection.close()

    def status_for_email(self, email: str) -> str | None:
        """Return 'pending'/'approved'/'denied' for an email, or None if no row."""
        with self.connect() as db:
            row = db.execute(
                "SELECT status FROM access_request WHERE email = ?", (email,)
            ).fetchone()
        return row["status"] if row else None

    def upsert_request(self, email: str, note: str | None) -> str:
        """Insert or reset a request to pending. Returns the status."""
        with self.connect() as db:
            existing = db.execute(
                "SELECT id, status FROM access_request WHERE email = ?", (email,)
            ).fetchone()
            now = int(time.time() * 1000)
            if existing and existing["status"] == "pending":
                return "pending"
            if existing:
                db.execute(
                    "UPDATE access_request SET note = ?, status = 'pending', "
                    "decided_at = NULL, decided_by = NULL, created_at = ? "
                    "WHERE id = ?",
                    (note, now, existing["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO access_request (id, email, note, status, created_at) "
                    "VALUES (?, ?, ?, 'pending', ?)",
                    (str(uuid.uuid4()), email, note, now),
                )
        return "pending"

    def decide(self, request_id: str, decision: str, operator: str | None) -> str | None:
        """Set status to 'approved' or 'denied'. Returns new status or None if not found."""
        if decision not in ("approve", "deny"):
            return None
        status = "approved" if decision == "approve" else "denied"
        with self.connect() as db:
            existing = db.execute(
                "SELECT id FROM access_request WHERE id = ?", (request_id,)
            ).fetchone()
            if not existing:
                return None
            now = int(time.time() * 1000)
            db.execute(
                "UPDATE access_request SET status = ?, decided_at = ?, decided_by = ? "
                "WHERE id = ?",
                (status, now, operator[:320] if operator else None, request_id),
            )
        return status