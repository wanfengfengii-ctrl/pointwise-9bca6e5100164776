from collections import defaultdict
from dataclasses import dataclass

from lake.merge.eligibility import VolumePair, can_close_key, can_finish_job
from lake.merge.winners import Winner, choose_side_winner
from lake.registry.requests import JobBinding


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
                           sides: VolumePair) -> PublicationPlan:
    if tuple(side.side_index for side in sides) != (0, 1):
        raise ValueError('publication evidence must follow the bound logical side order')
    grouped: dict[str, list] = defaultdict(list)
    for side in sides:
        for candidate in side.candidates:
            key = candidate.key
            if base_key is None or key > base_key:
                grouped[key].append(candidate)

    decisions = []
    for key in sorted(grouped):
        if not can_close_key(key, sides):
            break
        winner = choose_side_winner(grouped[key])
        decisions.append(KeyDecision(key, winner))

    finished = can_finish_job(sides, len(grouped) - len(decisions))
    return PublicationPlan(base_key, tuple(decisions), finished)
