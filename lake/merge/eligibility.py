from lake.intake.frontier import VolumeEvidence


VolumePair = tuple[VolumeEvidence, VolumeEvidence]


def can_close_key(key: str, volumes: VolumePair) -> bool:
    for volume in volumes:
        if volume.end_position is not None:
            continue
        frontier = volume.frontier_key
        if frontier is None or frontier <= key:
            return False
    return True


def can_finish_job(volumes: VolumePair, remaining_keys: int) -> bool:
    return remaining_keys == 0 and all(volume.end_position is not None for volume in volumes)
