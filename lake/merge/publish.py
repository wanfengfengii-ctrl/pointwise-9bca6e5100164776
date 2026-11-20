from dataclasses import dataclass
import sqlite3

from lake.merge.plan import PublicationPlan
from lake.registry.identity import JobId
from lake.source.records import encode_integer


class PublicationRejected(RuntimeError):
    """The publication was rolled back or its plan needs to be refreshed."""


@dataclass(frozen=True)
class PublicationState:
    last_key: str | None = None
    visible_count: int = 0
    finished: bool = False


class Publisher:
    def __init__(self, db: sqlite3.Connection, before_commit=None):
        self.db = db
        self.before_commit = before_commit

    def initialize(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS publication_state (
                job_id TEXT PRIMARY KEY NOT NULL REFERENCES jobs(job_id),
                last_key TEXT,
                visible_count INTEGER NOT NULL CHECK (visible_count >= 0),
                finished INTEGER NOT NULL CHECK (finished IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS decisions (
                job_id TEXT NOT NULL REFERENCES jobs(job_id),
                key TEXT NOT NULL,
                version TEXT NOT NULL,
                value TEXT,
                deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
                volume_id INTEGER NOT NULL REFERENCES volumes(volume_id),
                source_position INTEGER NOT NULL CHECK (source_position >= 0),
                origin TEXT NOT NULL,
                line_no INTEGER CHECK (line_no > 0),
                PRIMARY KEY (job_id, key),
                UNIQUE (job_id, line_no),
                CHECK ((value IS NULL) = deleted AND (line_no IS NULL) = deleted)
            );
        ''')

    def get_state(self, job_id: JobId) -> PublicationState:
        row = self.db.execute('''
            SELECT last_key, visible_count, finished FROM publication_state WHERE job_id = ?
        ''', (job_id,)).fetchone()
        if row is None:
            return PublicationState()
        return PublicationState(row['last_key'], row['visible_count'], bool(row['finished']))

    def commit_plan(self, job_id: JobId, plan: PublicationPlan) -> PublicationState:
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                return self._write_plan(job_id, plan)
        except sqlite3.OperationalError as exc:
            raise PublicationRejected(f'could not commit publication for {job_id!r}') from exc

    def _write_plan(self, job_id: JobId, plan: PublicationPlan) -> PublicationState:
        current = self.get_state(job_id)
        if current.finished:
            return current
        if current.last_key != plan.base_key:
            raise PublicationRejected('publication moved while the plan was being built')
        if not plan.decisions and not plan.finished:
            return current

        last_key = current.last_key
        count = current.visible_count
        for decision in plan.decisions:
            if last_key is not None and decision.key <= last_key:
                raise ValueError('publication must advance in strict key order')
            winner = decision.winner
            record = winner.record
            if record.key != decision.key:
                raise ValueError('winner key does not match its decision')
            value = None
            line_no = None
            if not record.deleted:
                count += 1
                value = encode_integer(record.value)
                line_no = count
            self.db.execute('''
                INSERT INTO decisions(job_id, key, version, value, deleted, volume_id,
                                      source_position, origin, line_no)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (job_id, decision.key, encode_integer(record.version), value, int(record.deleted),
                  winner.origin.volume_id, winner.origin.position, winner.origin.reference, line_no))
            last_key = decision.key

        self.db.execute('''
            INSERT INTO publication_state(job_id, last_key, visible_count, finished) VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET last_key = excluded.last_key,
                visible_count = excluded.visible_count, finished = excluded.finished
        ''', (job_id, last_key, count, int(plan.finished)))
        if self.before_commit is not None:
            self.before_commit(job_id)
        return PublicationState(last_key, count, plan.finished)
