from dataclasses import dataclass

from lake.registry.identity import VolumeId


@dataclass(frozen=True)
class MergePolicy:
    code: str

    def __post_init__(self):
        if self.code != 'version-volume-position-v1':
            raise ValueError(f'unsupported merge policy {self.code!r}')

    def volume_priority(self, volumes: tuple[VolumeId, VolumeId], volume_id: VolumeId) -> int:
        return volumes.index(volume_id)


DEFAULT_POLICY = MergePolicy('version-volume-position-v1')
