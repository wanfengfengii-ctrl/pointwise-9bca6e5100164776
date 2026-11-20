from dataclasses import dataclass

from lake.audit.positions import ReadPosition, next_position, validate_position
from lake.audit.provenance import AuditOrigin, format_origin
from lake.merge.publish import Publisher
from lake.merge.snapshot import load_published_snapshot
from lake.registry.ledger import RegistryLedger


@dataclass(frozen=True)
class ReadRow:
    key: str
    version: int
    value: int
    origin: AuditOrigin


@dataclass(frozen=True)
class ReadResult:
    rows: tuple[ReadRow, ...]
    next_position: ReadPosition
    finished: bool


def read(ledger: RegistryLedger, publisher: Publisher, job_id: str,
         position: ReadPosition | None = None) -> ReadResult:
    snapshot = load_published_snapshot(ledger, publisher, job_id)
    position = validate_position(snapshot.job_id, position, snapshot.state.visible_count)
    rows = tuple(ReadRow(row.key, row.version, row.value, format_origin(row))
                 for row in snapshot.rows[position.offset:])
    return ReadResult(rows, next_position(position, len(rows)), snapshot.state.finished)
