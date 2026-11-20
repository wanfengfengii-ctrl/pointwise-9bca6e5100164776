from dataclasses import dataclass

from lake.intake.takeover import Takeover
from lake.merge.plan import build_publication_plan
from lake.merge.publish import Publisher
from lake.merge.side import plain_side, switched_side
from lake.registry.identity import JobId
from lake.registry.requests import RequestRegistry
from lake.switch import Switchboard


@dataclass(frozen=True)
class StepResult:
    job_id: JobId
    visible_count: int
    finished: bool


def step(requests: RequestRegistry, takeover: Takeover, publisher: Publisher,
         switchboard: Switchboard, job_id: str) -> StepResult:
    binding = requests.get_binding(job_id)
    state = publisher.get_state(binding.job_id)
    if not state.finished:
        switch = switchboard.get_switch(binding.job_id)
        if switch is None:
            left = takeover.advance_volume(binding.job_id, binding.volumes[0])
            right = takeover.advance_volume(binding.job_id, binding.volumes[1])
            sides = (plain_side(0, left.evidence), plain_side(1, right.evidence))
        else:
            sides = _switched_sides(binding, switch, takeover)
        plan = build_publication_plan(binding, state.last_key, sides)
        state = publisher.commit_plan(binding.job_id, plan)
    return StepResult(binding.job_id, state.visible_count, state.finished)


def _switched_sides(binding, switch, takeover: Takeover):
    sides = []
    for side_index, volume_id in enumerate(binding.volumes):
        if side_index != switch.side:
            progress = takeover.advance_volume(binding.job_id, volume_id)
            sides.append(plain_side(side_index, progress.evidence))
            continue
        old_entries = takeover.retained_view(binding.job_id, switch.old_volume, switch.old_next)
        replacement = takeover.advance_replacement(binding.job_id, switch.replacement_volume)
        sides.append(switched_side(side_index, switch.old_volume, switch.old_next,
                                   old_entries, replacement.evidence))
    return tuple(sides)
