from dataclasses import dataclass

from lake.intake.journal import CustodyJournal
from lake.registry.identity import JobId, VolumeId
from lake.source.receipts import RetryableSource
from lake.source.volume import SourceVolume


@dataclass(frozen=True)
class RecoveryResult:
    reconciled: int
    failure: RetryableSource | None = None


def recover_pending_confirmations(journal: CustodyJournal, source: SourceVolume,
                                  job_id: JobId, volume_id: VolumeId) -> RecoveryResult:
    reconciled = 0
    for entry in journal.pending_confirmations(job_id, volume_id):
        token = entry.slot.confirmation_id
        try:
            receipt = source.confirmation_result(volume_id, token)
            if receipt is None:
                receipt = source.confirm(volume_id, token)
        except RetryableSource as exc:
            return RecoveryResult(reconciled, exc)
        journal.record_confirmation(job_id, receipt)
        reconciled += 1
    return RecoveryResult(reconciled)
