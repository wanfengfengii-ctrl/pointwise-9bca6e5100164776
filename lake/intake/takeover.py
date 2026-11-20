from dataclasses import dataclass

from lake.intake.frontier import VolumeEvidence, build_volume_evidence
from lake.intake.journal import CustodyJournal
from lake.intake.recovery import recover_pending_confirmations
from lake.registry.identity import JobId, VolumeId
from lake.source.cursor import PollResult
from lake.source.receipts import RetryableSource
from lake.source.volume import SourceVolume


@dataclass(frozen=True)
class IntakeProgress:
    evidence: VolumeEvidence
    last_poll: PollResult


class Takeover:
    def __init__(self, source: SourceVolume, journal: CustodyJournal):
        self.source = source
        self.journal = journal

    def advance_volume(self, job_id: JobId, volume_id: VolumeId) -> IntakeProgress:
        recovery = recover_pending_confirmations(self.journal, self.source, job_id, volume_id)
        if recovery.failure is not None:
            raise recovery.failure

        polled = self.source.poll(volume_id)
        while polled.kind == 'slot':
            slot = polled.slot
            if slot is None or slot.volume_id != volume_id or slot.position != polled.position:
                raise ValueError('source offered a slot outside the requested position or volume')
            entry = self.journal.save_record(job_id, slot)
            if not entry.confirmed:
                receipt = self.source.confirm(volume_id, slot.confirmation_id)
                self.journal.record_confirmation(job_id, receipt)
            polled = self.source.poll(volume_id)

        if polled.kind == 'end':
            self.journal.record_end(job_id, volume_id, polled.position)
        entries, observed_end = self.journal.read_view(job_id, volume_id)
        evidence = build_volume_evidence(volume_id, entries, observed_end)
        if polled.position > len(evidence.entries):
            raise RetryableSource(f'volume {volume_id} advanced beyond continuous custody')
        return IntakeProgress(evidence, polled)
