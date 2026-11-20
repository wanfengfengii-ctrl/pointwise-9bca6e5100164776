from collections.abc import Iterable
from dataclasses import dataclass

from lake.merge.publish import Publisher
from lake.merge.snapshot import PublishedRow, load_published_snapshot
from lake.registry.ledger import RegistryLedger


@dataclass(frozen=True)
class Balance:
    row_count: int
    total: int


def calculate_totals(rows: Iterable[PublishedRow]) -> Balance:
    count = 0
    total = 0
    for row in rows:
        count += 1
        total += row.value
    return Balance(count, total)


def balance(ledger: RegistryLedger, publisher: Publisher, job_id: str) -> Balance | None:
    snapshot = load_published_snapshot(ledger, publisher, job_id)
    if not snapshot.state.finished:
        return None
    return calculate_totals(snapshot.rows)
