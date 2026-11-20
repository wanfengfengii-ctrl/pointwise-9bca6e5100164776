from dataclasses import dataclass, field
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lake import Lake, PublicationRejected, RetryableSource, SourceRecord
from lake.source.volume import SourceVolume


@dataclass
class Interruptions:
    before_confirmation: set[str] = field(default_factory=set)
    after_confirmation: set[str] = field(default_factory=set)
    unreadable_receipts: set[str] = field(default_factory=set)
    rejected_jobs: set[str] = field(default_factory=set)

    def before_publish_commit(self, job_id):
        if job_id in self.rejected_jobs:
            self.rejected_jobs.remove(job_id)
            raise PublicationRejected(f'publication rejected at commit for {job_id}')


class InterruptedSource(SourceVolume):
    """Inject link interruptions around the real, independently committed source store."""

    def __init__(self, store, events):
        super().__init__(store)
        self.events = events

    def confirm(self, volume_id, confirmation_id):
        if confirmation_id in self.events.before_confirmation:
            self.events.before_confirmation.remove(confirmation_id)
            raise RetryableSource('confirmation did not reach the source')
        result = super().confirm(volume_id, confirmation_id)
        if confirmation_id in self.events.after_confirmation:
            self.events.after_confirmation.remove(confirmation_id)
            raise RetryableSource('confirmation was committed but its reply was lost')
        return result

    def confirmation_result(self, volume_id, confirmation_id):
        if confirmation_id in self.events.unreadable_receipts:
            raise RetryableSource('source receipts are temporarily unavailable')
        return super().confirmation_result(volume_id, confirmation_id)


def value(key, version, reading, origin):
    return SourceRecord(key, version, reading, False, origin)


def deletion(key, version, origin):
    return SourceRecord(key, version, None, True, origin)


class LakeCase(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory(prefix='north-lake-test-')))
        self.files = root / 'lake.sqlite', root / 'source.sqlite'
        self.events = Interruptions()
        self.lake = self.open_lake()

    def open_lake(self):
        return self.enterContext(Lake(
            *self.files,
            source_factory=lambda store: InterruptedSource(store, self.events),
            before_publish_commit=self.events.before_publish_commit,
        ))

    def reopen(self):
        self.lake.close()
        self.lake = self.open_lake()
        return self.lake

    def bind(self, left, right, *, job='day', left_available=None, right_available=None):
        first = self.lake.register('甲卷', left, available=left_available)
        second = self.lake.register('乙卷', right, available=right_available)
        self.lake.start(job, first, second)
        return first, second

    def bind_sample(self, sample_name):
        path = Path(__file__).resolve().parents[1] / 'samples' / sample_name
        sample = json.loads(path.read_text(encoding='utf-8'))
        volumes = []
        for side in ('first', 'second'):
            volume = sample[side]
            records = [SourceRecord(**row) for row in volume['records']]
            volumes.append(self.lake.register(volume['name'], records, available=volume['available']))
        job = sample['job_id']
        self.lake.start(job, *volumes)
        return job, *volumes

    def released(self, *volumes):
        for volume in volumes:
            self.lake.source.release(volume)


def row_fields(page):
    return [(row.key, row.version, row.value, row.origin.volume_id, row.origin.position,
             row.origin.reference) for row in page.rows]
