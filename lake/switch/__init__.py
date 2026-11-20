from dataclasses import dataclass
import sqlite3

from lake.intake.journal import CustodyJournal
from lake.merge.publish import PublicationRejected
from lake.registry.identity import JobId, VolumeId, is_volume_id, validate_text
from lake.registry.ledger import RegistryLedger
from lake.source.records import SourceSlot
from lake.source.receipts import RetryableSource
from lake.source.volume import SourceVolume


@dataclass(frozen=True)
class SwitchReceipt:
    job_id: JobId
    request_id: str
    side: int
    old_volume: VolumeId
    old_next: int
    replacement_volume: VolumeId


class Switchboard:
    def __init__(self, db: sqlite3.Connection, ledger: RegistryLedger, journal: CustodyJournal,
                 source: SourceVolume, before_commit=None):
        self.db = db
        self.ledger = ledger
        self.journal = journal
        self.source = source
        self.before_commit = before_commit

    def initialize(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS switches (
                job_id TEXT PRIMARY KEY NOT NULL REFERENCES jobs(job_id),
                request_id TEXT NOT NULL,
                side INTEGER NOT NULL CHECK (side IN (0, 1)),
                old_volume INTEGER NOT NULL REFERENCES volumes(volume_id),
                old_next INTEGER NOT NULL CHECK (old_next >= 0),
                replacement_volume INTEGER NOT NULL REFERENCES volumes(volume_id),
                CHECK (old_volume <> replacement_volume)
            );
        ''')

    def get_switch(self, job_id: JobId) -> SwitchReceipt | None:
        row = self.db.execute(
            'SELECT request_id, side, old_volume, old_next, replacement_volume '
            'FROM switches WHERE job_id = ?', (job_id,)
        ).fetchone()
        if row is None:
            return None
        return SwitchReceipt(job_id, row['request_id'], row['side'], VolumeId(row['old_volume']),
                             row['old_next'], VolumeId(row['replacement_volume']))

    def switch_volume(self, job_id: str, request_id: str, side: int,
                      expected_old_volume: VolumeId, expected_next: int,
                      replacement_volume: VolumeId) -> SwitchReceipt:
        job_id = validate_text(job_id, 'job id')
        request_id = validate_text(request_id, 'request id')
        if type(side) is not int or side not in (0, 1):
            raise ValueError('side must be the integer 0 or 1')
        if not is_volume_id(expected_old_volume) or not is_volume_id(replacement_volume):
            raise ValueError('volume numbers must be positive integers')
        if type(expected_next) is not int or expected_next < 0:
            raise ValueError('expected_next must be a non-negative integer')

        binding = self.ledger.get_job(job_id)
        if binding is None:
            raise KeyError(job_id)
        # An accepted request always reclaims the original receipt, including after completion.
        existing = self.get_switch(job_id)
        if existing is not None:
            return self._replay(existing, request_id, side, expected_old_volume,
                                expected_next, replacement_volume)

        old_volume = binding.volumes[side]
        if expected_old_volume != old_volume:
            raise ValueError('expected old volume does not match the bound side')
        if replacement_volume in binding.volumes:
            raise ValueError('replacement volume must differ from both bound volumes')
        # An unregistered replacement of legal id shape is an unknown volume.
        self.ledger.get_volume(replacement_volume)
        if self.journal.has_formal_end(old_volume):
            raise ValueError('this side already observed the formal end of its volume')
        if self.ledger_publisher_finished(job_id):
            raise ValueError('the job is already complete')

        preserved = self.journal.continuous_custody_count(old_volume)
        if expected_next != preserved:
            raise ValueError('the switch cutoff is stale and no longer matches retained custody')

        first_key = self._probe_replacement(replacement_volume)
        if expected_next > 0 and first_key is not None:
            tail = self.journal.read_prefix(job_id, old_volume, expected_next)
            if first_key < tail[-1].slot.record.key:
                raise ValueError('replacement first key must not fall before the retained tail key')

        receipt = SwitchReceipt(job_id, request_id, side, old_volume, expected_next,
                                replacement_volume)
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('''
                    INSERT INTO switches(job_id, request_id, side, old_volume, old_next,
                                         replacement_volume)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (job_id, request_id, side, old_volume, expected_next, replacement_volume))
                if self.before_commit is not None:
                    self.before_commit(job_id)
        except sqlite3.OperationalError as exc:
            raise PublicationRejected(f'could not commit switchover for {job_id!r}') from exc
        return receipt

    def _replay(self, existing: SwitchReceipt, request_id: str, side: int,
                expected_old_volume: VolumeId, expected_next: int,
                replacement_volume: VolumeId) -> SwitchReceipt:
        same = (
            request_id == existing.request_id
            and side == existing.side
            and expected_old_volume == existing.old_volume
            and expected_next == existing.old_next
            and replacement_volume == existing.replacement_volume
        )
        if not same:
            raise ValueError('this job already switched under a different request or parameters')
        return existing

    def _probe_replacement(self, replacement_volume: VolumeId) -> str | None:
        """Read physical slot zero or a formal empty end without confirming source slots."""
        entry = self.db.execute(
            'SELECT key FROM custody WHERE volume_id = ? AND position = 0', (replacement_volume,)
        ).fetchone()
        if entry is not None:
            return entry['key']
        if self.journal.has_formal_end(replacement_volume):
            return None
        polled = self.source.poll(replacement_volume)
        if polled.kind == 'slot':
            slot: SourceSlot = polled.slot
            if slot is None or slot.volume_id != replacement_volume or slot.position != 0:
                raise ValueError('replacement offered a slot outside physical position zero')
            return slot.record.key
        if polled.kind == 'end':
            return None
        raise RetryableSource(f'replacement volume {replacement_volume} is not readable yet')

    def ledger_publisher_finished(self, job_id: JobId) -> bool:
        row = self.db.execute(
            'SELECT finished FROM publication_state WHERE job_id = ?', (job_id,)
        ).fetchone()
        return row is not None and bool(row['finished'])
