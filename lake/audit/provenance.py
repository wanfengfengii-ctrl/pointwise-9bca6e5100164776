from dataclasses import dataclass

from lake.merge.snapshot import PublishedRow
from lake.registry.identity import VolumeId


@dataclass(frozen=True)
class AuditOrigin:
    volume_id: VolumeId
    position: int
    reference: str


def format_origin(row: PublishedRow) -> AuditOrigin:
    origin = row.origin
    return AuditOrigin(origin.volume_id, origin.position, origin.reference)
