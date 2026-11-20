from dataclasses import dataclass

from lake.intake.takeover import Takeover
from lake.merge.plan import build_publication_plan
from lake.merge.publish import Publisher
from lake.registry.identity import JobId
from lake.registry.requests import RequestRegistry


@dataclass(frozen=True)
class StepResult:
    job_id: JobId
    visible_count: int
    finished: bool


def step(requests: RequestRegistry, takeover: Takeover, publisher: Publisher,
         job_id: str) -> StepResult:
    binding = requests.get_binding(job_id)
    state = publisher.get_state(binding.job_id)
    if not state.finished:
        first, second = binding.volumes
        left = takeover.advance_volume(binding.job_id, first)
        right = takeover.advance_volume(binding.job_id, second)
        plan = build_publication_plan(binding, state.last_key, (left.evidence, right.evidence))
        state = publisher.commit_plan(binding.job_id, plan)
    return StepResult(binding.job_id, state.visible_count, state.finished)
