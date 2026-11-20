from dataclasses import dataclass
import sqlite3

from lake.registry.identity import JobId, VolumeId
from lake.source.receipts import ConfirmationReceipt
from lake.source.records import SourceSlot, decode_record, encode_record


@dataclass(frozen=True)
class CustodyEntry:
    slot: SourceSlot
    confirmed: bool


def _entry(row) -> CustodyEntry:
    slot = SourceSlot(VolumeId(row['volume_id']), row['position'],
                      row['confirmation_id'], decode_record(row))
    return CustodyEntry(slot, bool(row['confirmed']))


class CustodyJournal:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS custody (
                job_id TEXT NOT NULL REFERENCES jobs(job_id),
                volume_id INTEGER NOT NULL REFERENCES volumes(volume_id),
                position INTEGER NOT NULL CHECK (position >= 0),
                confirmation_id TEXT NOT NULL,
                key TEXT NOT NULL,
                version TEXT NOT NULL,
                value TEXT,
                deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
                origin TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
                PRIMARY KEY (job_id, volume_id, position),
                UNIQUE (volume_id, position),
                UNIQUE (volume_id, confirmation_id),
                CHECK ((value IS NULL) = deleted)
            );
            CREATE TABLE IF NOT EXISTS custody_ends (
                volume_id INTEGER PRIMARY KEY REFERENCES volumes(volume_id),
                end_position INTEGER NOT NULL CHECK (end_position >= 0)
            );
        ''')

    def _require_bound_volume(self, job_id: JobId, volume_id: VolumeId):
        bound = self.db.execute('''
            SELECT 1 FROM jobs WHERE job_id = ? AND ? IN (first_volume, second_volume)
        ''', (job_id, volume_id)).fetchone()
        if bound is None:
            raise ValueError(f'volume {volume_id} is outside job {job_id!r}')

    def save_record(self, job_id: JobId, slot: SourceSlot) -> CustodyEntry:
        self._require_bound_volume(job_id, slot.volume_id)
        with self.db:
            # A shared source slot can be retained only once. Every bound job can replay it.
            self.db.execute('''
                INSERT INTO custody(job_id, volume_id, position, confirmation_id,
                                    key, version, value, deleted, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(volume_id, position) DO NOTHING
            ''', (job_id, slot.volume_id, slot.position, slot.confirmation_id,
                  *encode_record(slot.record)))
            row = self.db.execute('SELECT * FROM custody WHERE volume_id = ? AND position = ?',
                                  (slot.volume_id, slot.position)).fetchone()
            entry = _entry(row)
            if entry.slot != slot:
                raise ValueError(f'conflicting source original {slot.volume_id}/{slot.position}')
            return entry

    def record_confirmation(self, job_id: JobId, receipt: ConfirmationReceipt):
        self._require_bound_volume(job_id, receipt.volume_id)
        with self.db:
            result = self.db.execute('''
                UPDATE custody SET confirmed = 1
                WHERE volume_id = ? AND position = ? AND confirmation_id = ?
            ''', (receipt.volume_id, receipt.position, receipt.confirmation_id))
            if result.rowcount != 1:
                raise ValueError('source receipt has no matching retained original')

    def record_end(self, job_id: JobId, volume_id: VolumeId, position: int):
        self._require_bound_volume(job_id, volume_id)
        with self.db:
            self.db.execute('''
                INSERT INTO custody_ends(volume_id, end_position) VALUES (?, ?)
                ON CONFLICT(volume_id) DO NOTHING
            ''', (volume_id, position))
            if self._end_position(volume_id) != position:
                raise ValueError(f'conflicting source ends for volume {volume_id}')

    def _end_position(self, volume_id: VolumeId) -> int | None:
        row = self.db.execute('SELECT end_position FROM custody_ends WHERE volume_id = ?',
                              (volume_id,)).fetchone()
        return row['end_position'] if row is not None else None

    def pending_confirmations(self, job_id: JobId, volume_id: VolumeId) -> tuple[CustodyEntry, ...]:
        self._require_bound_volume(job_id, volume_id)
        rows = self.db.execute('''
            SELECT * FROM custody WHERE volume_id = ? AND confirmed = 0 ORDER BY position
        ''', (volume_id,))
        return tuple(_entry(row) for row in rows)

    def read_entries(self, job_id: JobId, volume_id: VolumeId) -> tuple[CustodyEntry, ...]:
        self._require_bound_volume(job_id, volume_id)
        rows = self.db.execute('SELECT * FROM custody WHERE volume_id = ? ORDER BY position',
                               (volume_id,))
        return tuple(_entry(row) for row in rows)

    def read_view(self, job_id: JobId, volume_id: VolumeId):
        with self.db:
            self.db.execute('BEGIN')
            return self.read_entries(job_id, volume_id), self._end_position(volume_id)
