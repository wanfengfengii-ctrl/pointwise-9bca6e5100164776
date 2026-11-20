from dataclasses import dataclass

from lake.intake.frontier import VolumeEvidence
from lake.intake.journal import CustodyEntry
from lake.registry.identity import VolumeId
from lake.source.records import SourceSlot


@dataclass(frozen=True)
class SideCandidate:
    """A candidate on one logical side, with its position in that side's logical order."""
    slot: SourceSlot
    side_index: int
    logical_position: int

    @property
    def key(self) -> str:
        return self.slot.record.key


@dataclass(frozen=True)
class SideView:
    """The candidate domain of one logical side of a job."""
    side_index: int
    candidates: tuple[SideCandidate, ...]
    end_position: int | None

    @property
    def frontier_key(self) -> str | None:
        return self.candidates[-1].key if self.candidates else None


def plain_side(side_index: int, evidence: VolumeEvidence) -> SideView:
    candidates = tuple(
        SideCandidate(entry.slot, side_index, entry.slot.position)
        for entry in evidence.entries
    )
    return SideView(side_index, candidates, evidence.end_position)


def switched_side(side_index: int, old_volume: VolumeId, cutoff: int,
                  old_entries: tuple[CustodyEntry, ...],
                  replacement: VolumeEvidence) -> SideView:
    candidates = []
    previous_key = None
    for entry in old_entries:
        if entry.slot.volume_id != old_volume or entry.slot.position >= cutoff:
            raise ValueError('retained prefix escapes the switch cutoff')
        if previous_key is not None and entry.slot.record.key < previous_key:
            raise ValueError('retained originals violate source key order')
        candidates.append(SideCandidate(entry.slot, side_index, entry.slot.position))
        previous_key = entry.slot.record.key

    base = cutoff
    for offset, entry in enumerate(replacement.entries):
        if entry.slot.volume_id != replacement.volume_id or entry.slot.position != offset:
            raise ValueError('replacement custody must start at physical slot zero')
        if previous_key is not None and entry.slot.record.key < previous_key:
            raise ValueError('replacement originals violate the retained source order')
        candidates.append(SideCandidate(entry.slot, side_index, base + offset))
        previous_key = entry.slot.record.key
    return SideView(side_index, tuple(candidates), replacement.end_position)
