import unittest

from lake import PublicationRejected, RetryableSource, SwitchReceipt
from tests.fixture import LakeCase, row_fields, value


class SwitchoverTests(LakeCase):
    def prepare_switch(self, *, first_available=2, old_available=2,
                       replacement_available=None):
        first = self.lake.register('甲卷', [
            value('a', 2, 7, '甲/a'), value('b', 4, 40, '甲/b'),
        ], available=first_available)
        old = self.lake.register('乙卷', [
            value('a', 1, 5, '乙/a'), value('b', 2, 9, '乙/b-先'),
            value('b', 3, 11, '乙/b-保'), value('b', 5, 50, '乙/b-迟'),
        ], available=old_available)
        replacement = self.lake.register('乙补卷', [
            value('b', 4, 13, '乙补/b'), value('c', 1, 2, '乙补/c'),
        ], available=replacement_available)
        self.lake.start('day', first, old)
        return first, old, replacement

    def test_switch_first_side_and_reopen(self):
        first, old, replacement = self.prepare_switch(first_available=1)
        self.lake.step('day')  # first custody=1 (no end yet), old custody=2
        receipt = self.lake.switch_volume('day', 'req-1', 0, first, 1, replacement)
        self.assertEqual(receipt, SwitchReceipt('day', 'req-1', 0, first, 1, replacement))
        self.reopen()
        self.assertEqual(
            self.lake.switch_volume('day', 'req-1', 0, first, 1, replacement), receipt)
        self.lake.source.release(first)
        self.lake.source.release(old)
        self.lake.source.release(replacement)
        self.assertTrue(self.lake.step('day').finished)
        rows = row_fields(self.lake.read('day'))
        self.assertEqual([row[0] for row in rows], ['a', 'b', 'c'])
        self.assertEqual(rows[1], ('b', 5, 50, old, 3, '乙/b-迟'))
        self.assertEqual(rows[2], ('c', 1, 2, replacement, 1, '乙补/c'))

    def test_boolean_and_bad_shapes_rejected(self):
        first, old, replacement = self.prepare_switch()
        self.lake.step('day')
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', True, first, 2, replacement)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, True, replacement)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, -1, replacement)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', '  ', 1, old, 2, replacement)

    def test_unknown_job_and_unknown_replacement(self):
        first, old, replacement = self.prepare_switch()
        with self.assertRaises(KeyError):
            self.lake.switch_volume('missing', 'req', 1, old, 0, replacement)
        with self.assertRaises(KeyError):
            self.lake.switch_volume('day', 'req', 1, old, 0, replacement + 100)

    def test_wrong_old_volume_and_bound_replacement(self):
        first, old, replacement = self.prepare_switch()
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, first, 0, replacement)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 0, first, 0, old)

    def test_stale_cutoff_both_directions(self):
        first, old, replacement = self.prepare_switch()
        self.lake.step('day')  # old custody=2
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, 1, replacement)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, 3, replacement)

    def test_waiting_replacement_is_retryable_then_succeeds(self):
        first, old, replacement = self.prepare_switch(replacement_available=0)
        self.lake.step('day')
        with self.assertRaises(RetryableSource):
            self.lake.switch_volume('day', 'req', 1, old, 2, replacement)
        self.assertIsNone(self.lake.switchboard.get_switch('day'))
        self.lake.source.release(replacement, 1)
        receipt = self.lake.switch_volume('day', 'req', 1, old, 2, replacement)
        self.assertEqual(receipt.old_next, 2)

    def test_replay_rules_and_second_switch(self):
        first, old, replacement = self.prepare_switch()
        self.lake.step('day')
        receipt = self.lake.switch_volume('day', 'req', 1, old, 2, replacement)
        self.assertEqual(
            self.lake.switch_volume('day', 'req', 1, old, 2, replacement), receipt)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, 2, replacement + 1)
        spare = self.lake.register('丁卷', [])
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'other', 1, old, 2, replacement)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 0, first, 2, spare)

    def test_switch_after_formal_end_and_after_completion_rejected(self):
        first, old, replacement = self.prepare_switch()
        self.lake.source.release(first)
        self.lake.source.release(old)
        self.assertTrue(self.lake.step('day').finished)
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, 4, replacement)
        self.assertIsNone(self.lake.switchboard.get_switch('day'))

    def test_failed_commit_leaves_no_change(self):
        first, old, replacement = self.prepare_switch()
        self.lake.step('day')

        def reject(job_id):
            raise PublicationRejected('stop')

        self.lake.switchboard.before_commit = reject
        with self.assertRaises(PublicationRejected):
            self.lake.switch_volume('day', 'req', 1, old, 2, replacement)
        self.assertIsNone(self.lake.switchboard.get_switch('day'))
        self.lake.switchboard.before_commit = None
        receipt = self.lake.switch_volume('day', 'req', 1, old, 2, replacement)
        self.assertEqual(receipt.old_next, 2)

    def test_reverse_first_key_rejected(self):
        first = self.lake.register('甲卷', [value('a', 2, 7, '甲/a'), value('z', 1, 1, '甲/z')])
        old = self.lake.register('乙卷', [value('m', 1, 4, '乙/m')], available=1)
        backwards = self.lake.register('逆接卷', [value('a', 1, 9, '补/a')])
        self.lake.start('day', first, old)
        self.lake.step('day')
        with self.assertRaises(ValueError):
            self.lake.switch_volume('day', 'req', 1, old, 1, backwards)


if __name__ == '__main__':
    unittest.main()
