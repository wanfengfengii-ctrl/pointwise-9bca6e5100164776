from dataclasses import dataclass

from lake.intake.journal import CustodyEntry
from lake.registry.identity import VolumeId


@dataclass(frozen=True)
class VolumeEvidence:
    volume_id: VolumeId
    entries: tuple[CustodyEntry, ...]
    end_position: int | None

    @property
    def frontier_key(self) -> str | None:
        return self.entries[-1].slot.record.key if self.entries else None

    @property
    def frontier_position(self) -> int | None:
        return self.entries[-1].slot.position if self.entries else None


def build_volume_evidence(volume_id: VolumeId, entries: tuple[CustodyEntry, ...],
                          observed_end: int | None) -> VolumeEvidence:
    covered = 0
    previous_key = None
    for entry in entries:
        slot = entry.slot
        if slot.volume_id != volume_id:
            raise ValueError('custody evidence contains an original from another volume')
        if slot.position != covered:
            break
        if previous_key is not None and slot.record.key < previous_key:
            raise ValueError('custody originals violate source key order')
        previous_key = slot.record.key
        covered += 1

    # A durable successor can close earlier keys even before its own confirmation.
    # A formal end can cover the whole volume only when there is no custody gap.
    verified_end = observed_end if observed_end == len(entries) == covered else None
    return VolumeEvidence(volume_id, entries[:covered], verified_end)
