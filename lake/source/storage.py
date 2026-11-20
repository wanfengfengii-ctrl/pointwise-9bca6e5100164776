from collections.abc import Sequence
from contextlib import contextmanager
import sqlite3

from lake.registry.identity import VolumeId
from lake.source.records import SourceRecord, encode_record


def validate_release_count(count: int, previous: int, total: int):
    if type(count) is not int or not previous <= count <= total:
        raise ValueError(f'release count must be an integer between {previous} and {total}')


class SourceStore:
    def __init__(self, database):
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')

    def close(self):
        self.db.close()

    def initialize(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS source_volumes (
                volume_id INTEGER PRIMARY KEY,
                length INTEGER NOT NULL CHECK (length >= 0),
                next_position INTEGER NOT NULL DEFAULT 0,
                offered INTEGER NOT NULL DEFAULT 0 CHECK (offered IN (0, 1)),
                available INTEGER NOT NULL,
                end_ready INTEGER NOT NULL CHECK (end_ready IN (0, 1)),
                CHECK (0 <= next_position AND next_position <= available AND available <= length),
                CHECK (offered = 0 OR next_position < available),
                CHECK (end_ready = 0 OR available = length)
            );
            CREATE TABLE IF NOT EXISTS source_slots (
                volume_id INTEGER NOT NULL REFERENCES source_volumes(volume_id),
                position INTEGER NOT NULL,
                key TEXT NOT NULL,
                version TEXT NOT NULL,
                value TEXT,
                deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
                origin TEXT NOT NULL,
                PRIMARY KEY (volume_id, position),
                CHECK ((value IS NULL) = deleted)
            );
            CREATE TABLE IF NOT EXISTS source_receipts (
                volume_id INTEGER NOT NULL REFERENCES source_volumes(volume_id),
                confirmation_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (volume_id, confirmation_id),
                UNIQUE (volume_id, position)
            );
        ''')

    @contextmanager
    def transaction(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            yield self.db

    def install_slots(self, volume_id: VolumeId, records: Sequence[SourceRecord], *,
                      available: int | None = None):
        total = len(records)
        count = total if available is None else available
        validate_release_count(count, 0, total)
        with self.transaction() as db:
            db.execute('''
                INSERT INTO source_volumes(volume_id, length, available, end_ready)
                VALUES (?, ?, ?, ?)
            ''', (volume_id, total, count, int(available is None)))
            db.executemany('''
                INSERT INTO source_slots(volume_id, position, key, version, value, deleted, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', ((volume_id, position, *encode_record(record))
                  for position, record in enumerate(records)))

    def release(self, volume_id: VolumeId, count: int | None):
        with self.transaction() as db:
            row = db.execute('''
                SELECT length, available, end_ready FROM source_volumes WHERE volume_id = ?
            ''', (volume_id,)).fetchone()
            if row is None:
                raise KeyError(volume_id)
            new_count = row['length'] if count is None else count
            validate_release_count(new_count, row['available'], row['length'])
            db.execute('''
                UPDATE source_volumes SET available = ?, end_ready = ? WHERE volume_id = ?
            ''', (new_count, int(count is None or row['end_ready']), volume_id))
