from contextlib import ExitStack, closing
import sqlite3

from lake.audit.positions import ReadPosition as ReadPosition
from lake.audit.read import ReadResult as ReadResult
from lake.audit.read import read
from lake.audit.totals import Balance as Balance
from lake.audit.totals import balance
from lake.intake.journal import CustodyJournal
from lake.intake.takeover import Takeover
from lake.merge.advance import StepResult as StepResult
from lake.merge.advance import step
from lake.merge.publish import PublicationRejected as PublicationRejected
from lake.merge.publish import Publisher
from lake.registry.catalog import Catalog
from lake.registry.ledger import RegistryLedger
from lake.registry.requests import JobBinding as JobBinding
from lake.registry.requests import RequestRegistry
from lake.source.receipts import RetryableSource as RetryableSource
from lake.source.records import SourceRecord as SourceRecord
from lake.source.storage import SourceStore
from lake.source.volume import SourceVolume


class Lake:
    def __init__(self, database, source_database, *, source_factory=SourceVolume,
                 before_publish_commit=None, before_switch_commit=None):
        with ExitStack() as opening:
            self.db = opening.enter_context(closing(sqlite3.connect(database)))
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys = ON')

            source_store = opening.enter_context(closing(SourceStore(source_database)))
            source_store.initialize()
            self.source = source_factory(source_store)

            self.ledger = RegistryLedger(self.db)
            self.journal = CustodyJournal(self.db)
            self.publisher = Publisher(self.db, before_publish_commit)
            self.before_switch_commit = before_switch_commit
            self.ledger.initialize()
            self.journal.initialize()
            self.publisher.initialize()

            self.catalog = Catalog(self.ledger, self.source)
            self.requests = RequestRegistry(self.catalog, self.ledger)
            self.takeover = Takeover(self.source, self.journal)
            self._connections = opening.pop_all()

    def register(self, name, records, *, available=None):
        return self.catalog.register(name, records, available=available)

    def start(self, job_id, first, second):
        return self.requests.start(job_id, first, second)

    def step(self, job_id):
        return step(self.requests, self.takeover, self.publisher, job_id)

    def read(self, job_id, position=None):
        return read(self.ledger, self.publisher, job_id, position)

    def balance(self, job_id):
        return balance(self.ledger, self.publisher, job_id)

    def close(self):
        self._connections.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
