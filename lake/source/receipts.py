from dataclasses import dataclass

from lake.registry.identity import VolumeId


class RetryableSource(RuntimeError):
    """A source outcome could not be established by this call."""


@dataclass(frozen=True)
class ConfirmationReceipt:
    volume_id: VolumeId
    position: int
    confirmation_id: str


class ReceiptStore:
    def __init__(self, db):
        self.db = db

    def get(self, volume_id: VolumeId, confirmation_id: str) -> ConfirmationReceipt | None:
        row = self.db.execute('''
            SELECT position FROM source_receipts WHERE volume_id = ? AND confirmation_id = ?
        ''', (volume_id, confirmation_id)).fetchone()
        if row is None:
            return None
        return ConfirmationReceipt(volume_id, row['position'], confirmation_id)

    def record(self, receipt: ConfirmationReceipt):
        self.db.execute('''
            INSERT INTO source_receipts(volume_id, confirmation_id, position) VALUES (?, ?, ?)
        ''', (receipt.volume_id, receipt.confirmation_id, receipt.position))
