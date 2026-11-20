from collections.abc import Sequence

from lake.registry.identity import VolumeId
from lake.source.cursor import CursorStore, PollResult
from lake.source.receipts import ConfirmationReceipt, ReceiptStore
from lake.source.records import SourceRecord
from lake.source.storage import SourceStore


class SourceVolume:
    def __init__(self, store: SourceStore):
        self.store = store
        self.cursor = CursorStore(store.db)
        self.receipts = ReceiptStore(store.db)

    def install(self, volume_id: VolumeId, records: Sequence[SourceRecord], *,
                available: int | None = None):
        self.store.install_slots(volume_id, records, available=available)

    def release(self, volume_id: VolumeId, count: int | None = None):
        self.store.release(volume_id, count)

    def poll(self, volume_id: VolumeId) -> PollResult:
        with self.store.transaction():
            return self.cursor.poll(volume_id)

    def confirm(self, volume_id: VolumeId, confirmation_id: str) -> ConfirmationReceipt:
        with self.store.transaction():
            existing = self.receipts.get(volume_id, confirmation_id)
            if existing is not None:
                return existing
            position = self.cursor.reclaim(volume_id, confirmation_id)
            receipt = ConfirmationReceipt(volume_id, position, confirmation_id)
            self.receipts.record(receipt)
            return receipt

    def confirmation_result(self, volume_id: VolumeId,
                            confirmation_id: str) -> ConfirmationReceipt | None:
        return self.receipts.get(volume_id, confirmation_id)
