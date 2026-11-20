from lake.merge.side import SideView


VolumePair = tuple[SideView, SideView]


def can_close_key(key: str, sides: VolumePair) -> bool:
    for side in sides:
        if side.end_position is not None:
            continue
        frontier = side.frontier_key
        if frontier is None or frontier <= key:
            return False
    return True


def can_finish_job(sides: VolumePair, remaining_keys: int) -> bool:
    return remaining_keys == 0 and all(side.end_position is not None for side in sides)
