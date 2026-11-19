import sqlite3
from contextlib import contextmanager


class ArchiveStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.write_transaction():
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY NOT NULL,
                    revision_id TEXT NOT NULL,
                    payload BLOB NOT NULL
                )
            ''')

    @contextmanager
    def write_transaction(self):
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            yield

    def insert_artifact(self, artifact_id: str, revision_id: str, payload: bytes) -> None:
        self.connection.execute('''
            INSERT INTO artifacts (artifact_id, revision_id, payload) VALUES (?, ?, ?)
        ''', (artifact_id, revision_id, payload))

    def read_artifact_row(self, artifact_id: str):
        return self.connection.execute('''
            SELECT artifact_id, revision_id, payload FROM artifacts WHERE artifact_id = ?
        ''', (artifact_id,)).fetchone()

    def list_artifact_rows(self):
        return self.connection.execute('''
            SELECT artifact_id, revision_id FROM artifacts ORDER BY rowid
        ''').fetchall()
