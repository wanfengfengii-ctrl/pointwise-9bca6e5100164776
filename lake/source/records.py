from dataclasses import dataclass

from lake.registry.identity import VolumeId, validate_text


@dataclass(frozen=True)
class SourceRecord:
    key: str
    version: int
    value: int | None
    deleted: bool
    origin: str


@dataclass(frozen=True)
class RecordOrigin:
    volume_id: VolumeId
    position: int
    reference: str


@dataclass(frozen=True)
class SourceSlot:
    volume_id: VolumeId
    position: int
    confirmation_id: str
    record: SourceRecord

    @property
    def origin(self) -> RecordOrigin:
        return RecordOrigin(self.volume_id, self.position, self.record.origin)


def validate_record(record: SourceRecord):
    if not isinstance(record, SourceRecord):
        raise ValueError('expected a SourceRecord')
    validate_text(record.key, 'record key')
    validate_text(record.origin, 'record origin')
    if type(record.version) is not int or type(record.deleted) is not bool:
        raise ValueError('record requires an integer version and a boolean deletion flag')
    if record.deleted:
        if record.value is not None:
            raise ValueError('a deletion has no read value')
    elif type(record.value) is not int:
        raise ValueError('a live record requires an integer read value')


def encode_integer(value: int) -> str:
    # SQLite INTEGER is bounded. Hex text also avoids Python's decimal digit limit.
    return format(value, 'x')


def decode_integer(encoded: str) -> int:
    return int(encoded, 16)


def encode_record(record: SourceRecord) -> tuple:
    value = None if record.value is None else encode_integer(record.value)
    return record.key, encode_integer(record.version), value, int(record.deleted), record.origin


def decode_record(row) -> SourceRecord:
    value = None if row['value'] is None else decode_integer(row['value'])
    return SourceRecord(row['key'], decode_integer(row['version']), value,
                        bool(row['deleted']), row['origin'])
