import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS bookings (
 id INTEGER PRIMARY KEY,
 phone TEXT NOT NULL,
 doctor TEXT NOT NULL,
 day TEXT NOT NULL,
 time TEXT NOT NULL,
 created_at TEXT NOT NULL,
 cancelled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_slot
 ON bookings(doctor, day, time) WHERE cancelled_at IS NULL;
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY,
 phone TEXT NOT NULL,
 text TEXT NOT NULL,
 response TEXT NOT NULL
);
'''


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()
