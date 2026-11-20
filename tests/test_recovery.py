from lake import Balance, PublicationRejected, ReadPosition, RetryableSource
from tests.fixture import LakeCase, row_fields, value


class RecoveryTests(LakeCase):
    def test_ack_lost_after_reclaim(self):
        first, _ = self.bind([value('b', 1, 11, '甲/b')], [])
        slot = self.lake.source.poll(first).slot
        self.events.after_confirmation.add(slot.confirmation_id)
        with self.assertRaisesRegex(RetryableSource, 'reply was lost'):
            self.lake.step('day')
        self.assertEqual(self.lake.read('day').rows, ())
        self.assertEqual(self.lake.source.poll(first).kind, 'end')
        self.reopen()
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [('b', 1, 11, first, 0, '甲/b')])
        self.assertEqual(self.lake.balance('day'), Balance(1, 11))

    def test_source_receipt(self):
        first, _ = self.bind([value('b', 1, 11, '甲/b')], [])
        offered = self.lake.source.poll(first)
        self.assertEqual(self.lake.source.poll(first), offered)
        token = offered.slot.confirmation_id
        self.assertIsNone(self.lake.source.confirmation_result(first, token))
        with self.assertRaises(ValueError):
            self.lake.source.confirm(first, 'another confirmation')
        self.assertEqual(self.lake.source.poll(first), offered)
        self.events.after_confirmation.add(token)
        with self.assertRaises(RetryableSource):
            self.lake.step('day')
        self.reopen()
        source = self.lake.source
        end = source.poll(first)
        self.assertEqual((end.kind, end.position, end.slot), ('end', 1, None))
        self.assertIsNone(source.store.db.execute('''
            SELECT 1 FROM source_slots WHERE volume_id = ? AND position = ?
        ''', (first, 0)).fetchone())
        receipt = source.confirmation_result(first, token)
        self.assertEqual((receipt.volume_id, receipt.position, receipt.confirmation_id),
                         (first, 0, token))
        self.assertEqual(source.confirm(first, token), receipt)
        self.assertEqual(source.poll(first), end)

    def test_pending_confirmation(self):
        first, _ = self.bind([value('a', 2, 7, '甲/a')], [])
        slot = self.lake.source.poll(first).slot
        token = slot.confirmation_id
        self.events.before_confirmation.add(token)
        with self.assertRaisesRegex(RetryableSource, 'did not reach'):
            self.lake.step('day')
        self.reopen()
        pending = self.lake.journal.pending_confirmations('day', first)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].slot, slot)
        self.assertIsNone(self.lake.source.confirmation_result(first, token))
        self.assertEqual(self.lake.source.poll(first).slot, slot)

        self.events.unreadable_receipts.add(token)
        try:
            with self.assertRaisesRegex(RetryableSource, 'temporarily unavailable'):
                self.lake.step('day')
            self.assertEqual(self.lake.journal.pending_confirmations('day', first), pending)
            self.assertEqual(self.lake.read('day').next_position, ReadPosition('day'))
        finally:
            self.events.unreadable_receipts.remove(token)

        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(self.lake.journal.pending_confirmations('day', first), ())
        self.assertEqual(self.lake.source.confirmation_result(first, token).confirmation_id, token)
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 2, 7, first, 0, '甲/a')])

    def test_combined_incident(self):
        marker = 'LAKE_RETIRE_MERGE_MISMATCH'
        job, first, second = self.bind_sample('staged.json')
        self.lake.step(job)
        prefix = self.lake.read(job)
        self.assertEqual((row_fields(prefix), prefix.next_position.offset, prefix.finished),
                         ([], 0, False), marker)
        self.released(second)
        self.lake.step(job)
        self.assertEqual(self.lake.source.poll(second).kind, 'end')
        self.assertEqual(row_fields(self.lake.read(job)), [], marker)

        self.released(first)
        b_slot = self.lake.source.poll(first).slot
        self.assertEqual((b_slot.position, b_slot.record.key), (1, 'b'))
        self.events.after_confirmation.add(b_slot.confirmation_id)
        with self.assertRaisesRegex(RetryableSource, 'reply was lost'):
            self.lake.step(job)
        self.assertEqual(self.lake.source.poll(first).kind, 'end')
        self.assertEqual(self.lake.read(job), prefix, marker)
        self.reopen()
        receipt = self.lake.source.confirmation_result(first, b_slot.confirmation_id)
        self.assertEqual(receipt.position, 1)
        self.lake.step(job)
        result = self.lake.read(job, prefix.next_position)
        expected_rows = [('b', 1, 11, first, 1, '甲站/b')]
        self.assertEqual((row_fields(result), result.next_position.offset, result.finished,
                          self.lake.balance(job)), (expected_rows, 1, True, Balance(1, 11)), marker)
        self.assertEqual(self.lake.read(job).rows, result.rows, marker)
        self.assertEqual(self.lake.step(job).visible_count, 1, marker)

    def test_publish_commit_rejected(self):
        first, _ = self.bind([value('a', 1, 7, '甲/a')], [])
        self.events.rejected_jobs.add('day')
        with self.assertRaises(PublicationRejected):
            self.lake.step('day')
        self.assertEqual(self.lake.read('day').rows, ())
        self.assertEqual(self.lake.read('day').next_position, ReadPosition('day'))
        self.assertIsNone(self.lake.balance('day'))
        self.assertEqual(self.lake.source.poll(first).kind, 'end')
        self.reopen()
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 1, 7, first, 0, '甲/a')])
        self.assertEqual(self.lake.balance('day'), Balance(1, 7))

    def test_existing_prefix(self):
        job, first, second = self.bind_sample('day.json')
        self.lake.step(job)
        prefix = self.lake.read(job)
        self.assertEqual(row_fields(prefix), [('a', 2, 7, first, 0, '甲站/a')])
        waiting = self.lake.read(job, prefix.next_position)
        self.released(first, second)
        self.events.rejected_jobs.add(job)
        with self.assertRaises(PublicationRejected):
            self.lake.step(job)
        with self.open_lake() as reader:
            self.assertEqual(reader.read(job), prefix)
            self.assertEqual(reader.read(job, prefix.next_position), waiting)
            self.assertIsNone(reader.balance(job))
        self.reopen()
        self.assertTrue(self.lake.step(job).finished)
        final = self.lake.read(job, prefix.next_position)
        self.assertEqual(row_fields(final), [('b', 2, 13, second, 1, '乙站/b')])
        self.assertEqual(final.next_position, ReadPosition(job, 2))
        self.assertEqual(self.lake.step(job).visible_count, 2)
        self.assertEqual(self.lake.read(job).rows, (*prefix.rows, *final.rows))
        self.assertEqual(self.lake.balance(job), Balance(2, 20))
