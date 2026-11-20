from collections.abc import Iterable

from lake.registry.identity import VolumeId, validate_volume_name
from lake.registry.ledger import RegistryLedger, VolumeRegistration
from lake.source.records import SourceRecord, validate_record
from lake.source.storage import validate_release_count
from lake.source.volume import SourceVolume


class Catalog:
    def __init__(self, ledger: RegistryLedger, source: SourceVolume):
        self.ledger = ledger
        self.source = source

    def register(self, name: str, records: Iterable[SourceRecord], *,
                 available: int | None = None) -> VolumeId:
        name = validate_volume_name(name)
        originals = []
        previous_key = None
        for position, record in enumerate(records):
            validate_record(record)
            if previous_key is not None and record.key < previous_key:
                raise ValueError(f'keys out of order at source position {position}')
            originals.append(record)
            previous_key = record.key
        if available is not None:
            validate_release_count(available, 0, len(originals))

        volume_id = self.ledger.reserve_volume(name)
        self.source.install(volume_id, originals, available=available)
        self.ledger.activate_volume(volume_id)
        return volume_id

    def get_volume(self, volume_id: VolumeId) -> VolumeRegistration:
        registration = self.ledger.get_volume(volume_id)
        if registration is None:
            raise KeyError(volume_id)
        return registration
