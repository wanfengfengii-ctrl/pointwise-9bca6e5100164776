from lake import Balance, ReadPosition
from tests.fixture import LakeCase, deletion, row_fields, value


class AuditTests(LakeCase):
    def test_read_while_tail_waits(self):
        job, first, second = self.bind_sample('day.json')
        state = self.lake.step(job)
        self.assertEqual((state.visible_count, state.finished), (1, False))
        prefix = self.lake.read(job)
        self.assertEqual(row_fields(prefix), [('a', 2, 7, first, 0, '甲站/a')])
        self.assertEqual(prefix.next_position, ReadPosition(job, 1))
        self.assertIsNone(self.lake.balance(job))
        self.reopen()
        self.assertEqual(self.lake.read(job), prefix)
        waiting = self.lake.read(job, prefix.next_position)
        self.assertEqual(waiting.rows, ())
        self.assertEqual(waiting.next_position, prefix.next_position)
        self.released(first, second)
        self.assertTrue(self.lake.step(job).finished)
        self.reopen()
        tail = self.lake.read(job, prefix.next_position)
        self.assertEqual(row_fields(tail), [('b', 2, 13, second, 1, '乙站/b')])
        self.assertEqual(tail.next_position, ReadPosition(job, 2))
        self.assertEqual(self.lake.read(job).rows, (*prefix.rows, *tail.rows))

    def test_cross_job_position(self):
        job, first, second = self.bind_sample('day.json')
        self.lake.step(job)
        position = self.lake.read(job).next_position
        self.bind([value('a', 1, 6, '丙/a'), value('b', 1, 9, '丙/b')], [], job='other')
        self.lake.step('other')
        self.assertEqual(len(self.lake.read('other', ReadPosition('other', 1)).rows), 1)
        with self.assertRaises(ValueError):
            self.lake.read('other', position)
        self.released(first, second)
        self.reopen()
        self.lake.step(job)
        self.assertEqual(row_fields(self.lake.read(job, position)), [('b', 2, 13, second, 1, '乙站/b')])

    def test_position_bounds(self):
        self.bind([value('a', 1, 8, '甲/a')], [])
        with self.assertRaises(ValueError):
            self.lake.read('day', ReadPosition('day', 1))
        self.lake.step('day')
        for invalid in (-1, 2, True, 0.5):
            with self.subTest(offset=invalid), self.assertRaises(ValueError):
                self.lake.read('day', ReadPosition('day', invalid))
        terminal = ReadPosition('day', 1)
        page = self.lake.read('day', terminal)
        self.assertEqual((page.rows, page.next_position), ((), terminal))
        with self.assertRaises(KeyError):
            self.lake.read('unknown')
        with self.assertRaises(KeyError):
            self.lake.balance('unknown')

    def test_total_after_reopen(self):
        job, first, second = self.bind_sample('day.json')
        self.released(first, second)
        self.assertTrue(self.lake.step(job).finished)
        self.reopen()
        self.assertEqual(row_fields(self.lake.read(job)), [
            ('a', 2, 7, first, 0, '甲站/a'), ('b', 2, 13, second, 1, '乙站/b'),
        ])
        self.assertEqual(self.lake.balance(job), Balance(2, 20))

    def test_winner_origin(self):
        _, second = self.bind([value('a', 1, 7, '甲/a')], [value('a', 2, 13, '乙/a')])
        self.lake.step('day')
        self.reopen()
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 2, 13, second, 0, '乙/a')])
        self.assertEqual(self.lake.balance('day'), Balance(1, 13))

    def test_repeated_values(self):
        first, second = self.bind([value('a', 2, 11, '甲/a'), value('c', 1, 4, '甲/c')],
                                  [value('b', 1, 11, '乙/b'), deletion('c', 2, '乙/c-撤回')])
        self.lake.step('day')
        self.reopen()
        self.assertEqual(row_fields(self.lake.read('day')), [
            ('a', 2, 11, first, 0, '甲/a'), ('b', 1, 11, second, 0, '乙/b'),
        ])
        self.assertEqual(self.lake.balance('day'), Balance(2, 22))

    def test_integer_values(self):
        high = 1 << 20000
        first, second = self.bind([value('B', -3, 0, '甲/零'), value('b', high, high, '甲/大')],
                                  [value('a', 0, -3, '乙/负'), value('c', 1, -high, '乙/负大')])
        self.lake.step('day')
        self.reopen()
        self.assertEqual(row_fields(self.lake.read('day')), [
            ('B', -3, 0, first, 0, '甲/零'), ('a', 0, -3, second, 0, '乙/负'),
            ('b', high, high, first, 1, '甲/大'), ('c', 1, -high, second, 1, '乙/负大'),
        ])
        self.assertEqual(self.lake.balance('day'), Balance(4, -3))

    def test_empty_balance(self):
        self.bind([], [])
        self.assertIsNone(self.lake.balance('day'))
        self.assertTrue(self.lake.step('day').finished)
        self.reopen()
        self.assertEqual(self.lake.read('day').rows, ())
        self.assertEqual(self.lake.balance('day'), Balance(0, 0))
