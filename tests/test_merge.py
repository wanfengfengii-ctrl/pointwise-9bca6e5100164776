from lake import Balance, ReadPosition
from tests.fixture import LakeCase, deletion, row_fields, value


class MergeTests(LakeCase):
    def test_equal_versions(self):
        first, second = self.bind(
            [value('a', 3, 1, '甲/0'), value('a', 3, 2, '甲/1')],
            [value('a', 3, 9, '乙/0')],
        )
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 3, 9, second, 0, '乙/0')])
        empty = self.lake.register('空卷', [])
        self.lake.start('solo', first, empty)
        self.assertTrue(self.lake.step('solo').finished)
        self.assertEqual(row_fields(self.lake.read('solo')), [('a', 3, 2, first, 1, '甲/1')])

    def test_tie_order(self):
        first, second = self.bind(
            [value('a', 2, 7, '甲/a'), value('b', 4, 10, '甲/b-早'), value('b', 4, 11, '甲/b-晚')],
            [value('a', 2, 9, '乙/a'), value('b', 3, 20, '乙/b')],
            left_available=0,
        )
        self.assertFalse(self.lake.step('day').finished)
        self.assertEqual(self.lake.read('day').rows, ())
        self.released(first)
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [
            ('a', 2, 9, second, 0, '乙/a'), ('b', 4, 11, first, 2, '甲/b-晚'),
        ])

    def test_empty_volume(self):
        first, second = self.bind([], [value('a', 1, 6, '乙/a')], left_available=0)
        self.assertEqual(self.lake.source.poll(first).kind, 'waiting')
        self.assertFalse(self.lake.step('day').finished)
        self.assertEqual(self.lake.read('day').rows, ())
        self.released(first)
        self.assertEqual(self.lake.source.poll(first).kind, 'end')
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 1, 6, second, 0, '乙/a')])

    def test_paused_equal_key(self):
        first, second = self.bind(
            [value('a', 2, 7, '甲/a'), value('b', 1, 11, '甲/b')],
            [value('a', 1, 5, '乙/a'), deletion('a', 3, '乙/a-撤回')],
            right_available=1,
        )
        state = self.lake.step('day')
        self.assertEqual((state.visible_count, state.finished), (0, False))
        self.assertEqual(self.lake.read('day').rows, ())
        self.released(second)
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [('b', 1, 11, first, 1, '甲/b')])

    def test_strict_boundary(self):
        first, second = self.bind(
            [value('a', 2, 7, '甲/a'), value('b', 1, 11, '甲/b')],
            [value('a', 1, 5, '乙/a'), value('a', 2, 9, '乙/a-晚'), value('b', 1, 13, '乙/b')],
            left_available=2, right_available=1,
        )
        self.lake.step('day')
        self.assertEqual(self.lake.read('day').rows, ())
        self.lake.source.release(second, 2)
        self.lake.step('day')
        self.assertEqual(self.lake.read('day').rows, ())
        self.lake.source.release(second, 3)
        state = self.lake.step('day')
        self.assertEqual((state.visible_count, state.finished), (1, False))
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 2, 9, second, 1, '乙/a-晚')])
        self.released(first, second)
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day', ReadPosition('day', 1))),
                         [('b', 1, 13, second, 2, '乙/b')])

    def test_delete_only_completion(self):
        _, second = self.bind([value('a', 2, 7, '甲/a')],
                              [value('a', 1, 5, '乙/a'), deletion('a', 3, '乙/a-撤回')],
                              right_available=1)
        self.assertFalse(self.lake.step('day').finished)
        self.assertIsNone(self.lake.publisher.get_state('day').last_key)
        self.released(second)
        done = self.lake.step('day')
        self.assertEqual((done.visible_count, done.finished), (0, True))
        self.assertEqual(self.lake.publisher.get_state('day').last_key, 'a')
        self.reopen()
        self.assertEqual(self.lake.step('day'), done)
        self.assertEqual(self.lake.read('day').next_position, ReadPosition('day'))
        self.assertEqual(self.lake.balance('day'), Balance(0, 0))
