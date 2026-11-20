"""SQLite persistence for the local workspace."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    current_version_id TEXT REFERENCES versions(version_id),
    head_epoch INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS versions (
    version_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    version_number INTEGER NOT NULL,
    parent_version_id TEXT REFERENCES versions(version_id),
    source_file TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_format TEXT NOT NULL,
    created_at TEXT NOT NULL,
    files TEXT NOT NULL,
    upload_hash TEXT,
    preview_file TEXT,
    freshness TEXT NOT NULL DEFAULT 'CURRENT',
    UNIQUE(asset_id, version_number)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES versions(version_id),
    operation_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELED')),
    input_files TEXT NOT NULL,
    output_files TEXT NOT NULL DEFAULT '[]',
    parameters TEXT NOT NULL,
    nodes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    output_version_id TEXT REFERENCES versions(version_id),
    retry_of TEXT REFERENCES runs(run_id),
    head_epoch INTEGER NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    freshness TEXT NOT NULL DEFAULT 'CURRENT',
    adapter_mode TEXT,
    export_file TEXT
);
CREATE INDEX IF NOT EXISTS runs_queue ON runs(status, created_at, run_id);
CREATE INDEX IF NOT EXISTS runs_version ON runs(asset_version_id, created_at);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES versions(version_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    ruleset_version TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_version ON reports(asset_version_id, created_at);
CREATE TABLE IF NOT EXISTS processing_baselines (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    asset_version_id TEXT NOT NULL REFERENCES versions(version_id),
    ruleset_version TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES versions(version_id),
    report_id TEXT NOT NULL REFERENCES reports(report_id),
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_version ON reviews(asset_version_id, created_at);
"""
JSON_COLUMNS = {"files", "input_files", "output_files", "parameters", "nodes", "summary", "findings"}


def clock():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def identifier():
    return uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def record(row):
    if row is None:
        return None
    return {key: json.loads(value) if key in JSON_COLUMNS else value for key, value in dict(row).items()}


class Database:
    """Open one short-lived connection per request or worker transaction."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "workspace.sqlite"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
