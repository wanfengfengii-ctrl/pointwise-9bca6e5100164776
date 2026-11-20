from dataclasses import dataclass

from lake.merge.publish import PublicationState, Publisher
from lake.registry.identity import JobId, VolumeId, validate_job_id
from lake.registry.ledger import RegistryLedger
from lake.source.records import RecordOrigin, decode_integer


@dataclass(frozen=True)
class PublishedRow:
    line_no: int
    key: str
    version: int
    value: int
    origin: RecordOrigin


@dataclass(frozen=True)
class PublishedSnapshot:
    job_id: JobId
    state: PublicationState
    rows: tuple[PublishedRow, ...]


def load_published_snapshot(ledger: RegistryLedger, publisher: Publisher,
                            job_id: str) -> PublishedSnapshot:
    job_id = validate_job_id(job_id)
    db = ledger.db
    if publisher.db is not db:
        raise ValueError('registry and publisher must share a snapshot connection')
    with db:
        db.execute('BEGIN')
        if ledger.get_job(job_id) is None:
            raise KeyError(job_id)
        state = publisher.get_state(job_id)
        records = db.execute('''
            SELECT line_no, key, version, value, volume_id, source_position, origin
            FROM decisions WHERE job_id = ? AND line_no IS NOT NULL ORDER BY line_no
        ''', (job_id,))
        rows = []
        for expected_line, record in enumerate(records, start=1):
            if record['line_no'] != expected_line:
                raise ValueError('published line sequence is incomplete')
            origin = RecordOrigin(VolumeId(record['volume_id']), record['source_position'],
                                  record['origin'])
            rows.append(PublishedRow(expected_line, record['key'], decode_integer(record['version']),
                                     decode_integer(record['value']), origin))
        if len(rows) != state.visible_count:
            raise ValueError('published lines and the read boundary disagree')
        return PublishedSnapshot(job_id, state, tuple(rows))
