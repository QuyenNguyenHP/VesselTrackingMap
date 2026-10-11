import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DATABASE_PATH", "fleet.db")


def initialize() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS vessels (
                imo TEXT PRIMARY KEY,
                mmsi TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                drums_ship_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mmsi TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                speed REAL,
                course REAL,
                source_at TEXT,
                received_at TEXT NOT NULL,
                FOREIGN KEY (mmsi) REFERENCES vessels(mmsi) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_positions_mmsi_id
                ON positions(mmsi, id DESC);
        """)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

