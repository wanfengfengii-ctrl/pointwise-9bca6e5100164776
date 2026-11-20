from collections import defaultdict
from dataclasses import dataclass

from lake.merge.eligibility import VolumePair, can_close_key, can_finish_job
from lake.merge.winners import Winner, choose_winner
from lake.registry.requests import JobBinding
from lake.source.records import SourceSlot


@dataclass(frozen=True)
class KeyDecision:
    key: str
    winner: Winner


@dataclass(frozen=True)
class PublicationPlan:
    base_key: str | None
    decisions: tuple[KeyDecision, ...]
    finished: bool


def build_publication_plan(binding: JobBinding, base_key: str | None,
                           evidence: VolumePair) -> PublicationPlan:
    if tuple(volume.volume_id for volume in evidence) != binding.volumes:
        raise ValueError('publication evidence must follow the bound volume order')
    grouped: dict[str, list[SourceSlot]] = defaultdict(list)
    for volume in evidence:
        for entry in volume.entries:
            key = entry.slot.record.key
            if base_key is None or key > base_key:
                grouped[key].append(entry.slot)

    decisions = []
    for key in sorted(grouped):
        if not can_close_key(key, evidence):
            break
        winner = choose_winner(grouped[key], binding.policy, binding.volumes)
        decisions.append(KeyDecision(key, winner))

    finished = can_finish_job(evidence, len(grouped) - len(decisions))
    return PublicationPlan(base_key, tuple(decisions), finished)
