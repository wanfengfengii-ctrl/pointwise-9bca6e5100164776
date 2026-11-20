from dataclasses import dataclass
import sqlite3

from lake.registry.identity import JobId, VolumeId, is_volume_id
from lake.registry.policy import MergePolicy


@dataclass(frozen=True)
class VolumeRegistration:
    volume_id: VolumeId
    name: str


@dataclass(frozen=True)
class JobBinding:
    job_id: JobId
    volumes: tuple[VolumeId, VolumeId]
    policy: MergePolicy


class RegistryLedger:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS volumes (
                volume_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY NOT NULL,
                first_volume INTEGER NOT NULL REFERENCES volumes(volume_id),
                second_volume INTEGER NOT NULL REFERENCES volumes(volume_id),
                policy TEXT NOT NULL,
                CHECK (first_volume <> second_volume)
            );
        ''')

    def reserve_volume(self, name: str) -> VolumeId:
        with self.db:
            cursor = self.db.execute('INSERT INTO volumes(name) VALUES (?)', (name,))
            return VolumeId(cursor.lastrowid)

    def activate_volume(self, volume_id: VolumeId):
        with self.db:
            result = self.db.execute(
                'UPDATE volumes SET active = 1 WHERE volume_id = ?', (volume_id,)
            )
            if result.rowcount != 1:
                raise KeyError(volume_id)

    def get_volume(self, volume_id: VolumeId) -> VolumeRegistration | None:
        if not is_volume_id(volume_id):
            return None
        row = self.db.execute(
            'SELECT name FROM volumes WHERE volume_id = ? AND active = 1', (volume_id,)
        ).fetchone()
        if row is None:
            return None
        return VolumeRegistration(volume_id, row['name'])

    def get_job(self, job_id: JobId) -> JobBinding | None:
        row = self.db.execute(
            'SELECT first_volume, second_volume, policy FROM jobs WHERE job_id = ?', (job_id,)
        ).fetchone()
        if row is None:
            return None
        volumes = (VolumeId(row['first_volume']), VolumeId(row['second_volume']))
        return JobBinding(job_id, volumes, MergePolicy(row['policy']))

    def put_job_if_absent(self, binding: JobBinding) -> JobBinding:
        with self.db:
            self.db.execute('''
                INSERT INTO jobs(job_id, first_volume, second_volume, policy)
                VALUES (?, ?, ?, ?) ON CONFLICT(job_id) DO NOTHING
            ''', (binding.job_id, *binding.volumes, binding.policy.code))
            return self.get_job(binding.job_id)
