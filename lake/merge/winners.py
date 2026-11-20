from collections.abc import Iterable
from dataclasses import dataclass

from lake.registry.identity import VolumeId
from lake.registry.policy import MergePolicy
from lake.source.records import RecordOrigin, SourceRecord, SourceSlot


@dataclass(frozen=True)
class Winner:
    record: SourceRecord
    origin: RecordOrigin


def choose_winner(candidates: Iterable[SourceSlot], policy: MergePolicy,
                  volumes: tuple[VolumeId, VolumeId]) -> Winner:
    def rank(slot: SourceSlot):
        return slot.record.version, policy.volume_priority(volumes, slot.volume_id), slot.position

    slot = max(candidates, key=rank)
    return Winner(slot.record, slot.origin)
