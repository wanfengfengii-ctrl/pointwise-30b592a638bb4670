import sqlite3
from contextlib import contextmanager


class HandoverStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with self.write_transaction():
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS handover_confirmations (
                    receipt_id TEXT PRIMARY KEY NOT NULL,
                    shift_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    manifest BLOB NOT NULL,
                    UNIQUE (shift_id, artifact_id)
                )
            ''')

    @contextmanager
    def write_transaction(self):
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            yield

    def read_confirmation(self, shift_id: str, artifact_id: str):
        return self.connection.execute('''
            SELECT receipt_id, shift_id, artifact_id, manifest
            FROM handover_confirmations WHERE shift_id = ? AND artifact_id = ?
        ''', (shift_id, artifact_id)).fetchone()

    def read_by_receipt(self, receipt_id: str):
        return self.connection.execute('''
            SELECT receipt_id, shift_id, artifact_id, manifest
            FROM handover_confirmations WHERE receipt_id = ?
        ''', (receipt_id,)).fetchone()

    def list_by_shift(self, shift_id: str):
        return self.connection.execute('''
            SELECT receipt_id, shift_id, artifact_id, manifest
            FROM handover_confirmations WHERE shift_id = ? ORDER BY rowid
        ''', (shift_id,)).fetchall()

    def insert_confirmation(
        self, receipt_id: str, shift_id: str, artifact_id: str, manifest: bytes
    ) -> None:
        self.connection.execute('''
            INSERT INTO handover_confirmations (receipt_id, shift_id, artifact_id, manifest)
            VALUES (?, ?, ?, ?)
        ''', (receipt_id, shift_id, artifact_id, manifest))
