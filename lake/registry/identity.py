from typing import NewType


VolumeId = NewType('VolumeId', int)
JobId = NewType('JobId', str)


def validate_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonblank string')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError(f'{field} must be encodable as UTF-8') from exc
    return value


def validate_volume_name(name: str) -> str:
    return validate_text(name, 'volume name')


def validate_job_id(job_id: str) -> JobId:
    return JobId(validate_text(job_id, 'job id'))


def is_volume_id(value: object) -> bool:
    return type(value) is int and 0 < value < (1 << 63)
