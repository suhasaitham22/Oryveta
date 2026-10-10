"""SQLite v0.1 operational store, explicitly scoped by authenticated account."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DDL = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, github_id TEXT UNIQUE, login TEXT NOT NULL,
  display_name TEXT NOT NULL, avatar_url TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  expires_at REAL NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
  state_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, brief TEXT NOT NULL, blueprint TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'scaffolded', origin TEXT NOT NULL DEFAULT 'new',
  source_url TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_analyses (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  result_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS project_analyses_project_idx ON project_analyses(project_id,created_at);
CREATE INDEX IF NOT EXISTS projects_owner_idx ON projects(user_id,created_at);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  project_id TEXT REFERENCES projects(id), kind TEXT NOT NULL,
  challenge TEXT, seed INTEGER, status TEXT NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL, lease_token TEXT,
  result_json TEXT, error TEXT, idempotency_key TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE(user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs(status, lease_until, created_at);
CREATE TABLE IF NOT EXISTS ai_calls (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  day_utc TEXT NOT NULL, status TEXT NOT NULL,
  reserved_tokens INTEGER NOT NULL, charged_tokens INTEGER NOT NULL DEFAULT 0,
  expires_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_calls_owner_day_idx ON ai_calls(user_id,day_utc);
CREATE INDEX IF NOT EXISTS ai_calls_expiry_idx ON ai_calls(status,expires_at);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users(id), job_id TEXT REFERENCES jobs(id),
  kind TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_user_idx ON events(user_id, created_at);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            # WAL is a database-wide setting. Apply it once at initialization,
            # not on every request/worker connection (which can take a write lock).
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(DDL)
            # Non-destructive upgrade for earlier local previews.
            cols = {x["name"] for x in conn.execute("PRAGMA table_info(projects)")}
            if "origin" not in cols:
                conn.execute("ALTER TABLE projects ADD COLUMN origin TEXT NOT NULL DEFAULT 'new'")
            if "source_url" not in cols:
                conn.execute("ALTER TABLE projects ADD COLUMN source_url TEXT")
            job_cols = {x["name"] for x in conn.execute("PRAGMA table_info(jobs)")}
            if "lease_token" not in job_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN lease_token TEXT")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    def add_event(self, user_id: str, kind: str, detail: str, job_id: str | None = None):
        with self.connect() as conn:
            conn.execute("INSERT INTO events(user_id,job_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
                         (user_id, job_id, kind, detail, time.time()))
