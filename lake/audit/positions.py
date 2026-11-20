from dataclasses import dataclass

from lake.registry.identity import JobId


@dataclass(frozen=True)
class ReadPosition:
    job_id: JobId
    offset: int = 0


def validate_position(job_id: JobId, position: ReadPosition | None,
                      visible_count: int) -> ReadPosition:
    if position is None:
        return ReadPosition(job_id)
    if not isinstance(position, ReadPosition) or position.job_id != job_id:
        raise ValueError('read position does not belong to this job')
    if type(position.offset) is not int or not 0 <= position.offset <= visible_count:
        raise ValueError('read position is outside the published boundary')
    return position


def next_position(position: ReadPosition, delivered: int) -> ReadPosition:
    if delivered == 0:
        return position
    return ReadPosition(position.job_id, position.offset + delivered)
