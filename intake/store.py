import sqlite3
from contextlib import contextmanager


class IntakeStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.write_transaction():
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS grid_revisions (
                    revision_id TEXT PRIMARY KEY NOT NULL,
                    batch_id TEXT NOT NULL,
                    predecessor TEXT,
                    vertices TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS batch_heads (
                    batch_id TEXT PRIMARY KEY NOT NULL,
                    revision_id TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS grid_sources (
                    revision_id TEXT PRIMARY KEY NOT NULL,
                    disabled INTEGER NOT NULL CHECK (disabled IN (0, 1))
                )
            ''')

    @contextmanager
    def write_transaction(self):
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            yield

    def read_batch_head(self, batch_id: str) -> str | None:
        row = self.connection.execute(
            'SELECT revision_id FROM batch_heads WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        return None if row is None else row[0]

    def read_revision_row(self, revision_id: str):
        return self.connection.execute('''
            SELECT r.revision_id, r.batch_id, r.predecessor, r.vertices, s.disabled
            FROM grid_revisions AS r
            JOIN grid_sources AS s ON s.revision_id = r.revision_id
            WHERE r.revision_id = ?
        ''', (revision_id,)).fetchone()

    def append_revision_row(
        self, revision_id: str, batch_id: str, predecessor: str | None, vertices: str
    ) -> None:
        self.connection.execute('''
            INSERT INTO grid_revisions (revision_id, batch_id, predecessor, vertices)
            VALUES (?, ?, ?, ?)
        ''', (revision_id, batch_id, predecessor, vertices))
        self.connection.execute(
            'INSERT INTO grid_sources (revision_id, disabled) VALUES (?, 0)', (revision_id,)
        )
        self.connection.execute('''
            INSERT INTO batch_heads (batch_id, revision_id) VALUES (?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET revision_id = excluded.revision_id
        ''', (batch_id, revision_id))

    def set_source_disabled(self, revision_id: str) -> bool:
        update = self.connection.execute(
            'UPDATE grid_sources SET disabled = 1 WHERE revision_id = ?', (revision_id,)
        )
        return update.rowcount == 1

    def list_revision_ids(self, batch_id: str | None = None) -> tuple[str, ...]:
        if batch_id is None:
            rows = self.connection.execute('SELECT revision_id FROM grid_revisions ORDER BY rowid')
        else:
            rows = self.connection.execute('''
                SELECT revision_id FROM grid_revisions WHERE batch_id = ? ORDER BY rowid
            ''', (batch_id,))
        return tuple(row[0] for row in rows)
