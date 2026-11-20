from dataclasses import dataclass
from typing import Literal

from lake.registry.identity import VolumeId
from lake.source.records import SourceSlot, decode_record


@dataclass(frozen=True)
class PollResult:
    kind: Literal['slot', 'waiting', 'end']
    position: int
    slot: SourceSlot | None = None


def _confirmation_id(volume_id: VolumeId, position: int) -> str:
    return f'{volume_id}/{position}'


class CursorStore:
    def __init__(self, db):
        self.db = db

    def _state(self, volume_id: VolumeId):
        row = self.db.execute('SELECT * FROM source_volumes WHERE volume_id = ?',
                              (volume_id,)).fetchone()
        if row is None:
            raise KeyError(volume_id)
        return row

    def poll(self, volume_id: VolumeId) -> PollResult:
        state = self._state(volume_id)
        position = state['next_position']
        if position == state['length'] and state['end_ready']:
            return PollResult('end', position)
        if position >= state['available']:
            return PollResult('waiting', position)
        row = self.db.execute('''
            SELECT key, version, value, deleted, origin FROM source_slots
            WHERE volume_id = ? AND position = ?
        ''', (volume_id, position)).fetchone()
        if row is None:
            raise ValueError(f'missing source slot {volume_id}/{position}')
        if not state['offered']:
            self.db.execute('UPDATE source_volumes SET offered = 1 WHERE volume_id = ?',
                            (volume_id,))
        slot = SourceSlot(volume_id, position, _confirmation_id(volume_id, position),
                          decode_record(row))
        return PollResult('slot', position, slot)

    def reclaim(self, volume_id: VolumeId, confirmation_id: str) -> int:
        state = self._state(volume_id)
        position = state['next_position']
        if not state['offered'] or confirmation_id != _confirmation_id(volume_id, position):
            raise ValueError('confirmation does not name the offered slot')
        deletion = self.db.execute('DELETE FROM source_slots WHERE volume_id = ? AND position = ?',
                                   (volume_id, position))
        if deletion.rowcount != 1:
            raise ValueError('offered source slot is missing')
        self.db.execute('''
            UPDATE source_volumes SET next_position = ?, offered = 0 WHERE volume_id = ?
        ''', (position + 1, volume_id))
        return position
