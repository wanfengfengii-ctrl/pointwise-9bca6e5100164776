from lake import SourceRecord
from tests.fixture import LakeCase, row_fields, value


class RegistrationTests(LakeCase):
    def test_same_request(self):
        first, second = self.bind([], [])
        binding = self.lake.requests.get_binding('day')
        self.assertEqual(binding.volumes, (first, second))
        self.assertEqual(self.lake.start('day', first, second), binding)

    def test_init_reopen(self):
        first, second = self.bind([value('a', 1, 8, '甲/a')], [], left_available=0)
        additional = self.lake.register('白班补登卷', [value('c', 1, 6, '丙/c')])
        binding = self.lake.requests.get_binding('day')
        self.assertFalse(self.lake.step('day').finished)
        self.reopen()
        self.reopen()
        self.assertEqual(self.lake.catalog.get_volume(additional).name, '白班补登卷')
        self.assertEqual(self.lake.start('day', first, second), binding)
        self.assertEqual(self.lake.source.poll(first).kind, 'waiting')
        self.released(first)
        self.assertTrue(self.lake.step('day').finished)
        original = self.lake.read('day')
        self.reopen()
        self.assertEqual(self.lake.read('day'), original)

    def test_inverted_keys(self):
        valid = self.lake.register('有效卷', [value('q', 1, 4, '原/q')])
        with self.assertRaisesRegex(ValueError, 'out of order'):
            self.lake.register('逆序卷', [value('b', 1, 3, '坏/b'), value('a', 1, 2, '坏/a')])
        with self.assertRaises(KeyError):
            self.lake.catalog.get_volume(valid + 1)
        self.assertEqual(self.lake.catalog.get_volume(valid).name, '有效卷')
        self.assertEqual(self.lake.source.poll(valid).slot.record.value, 4)

    def test_record_shape(self):
        bad_records = [
            SourceRecord('', 1, 7, False, '甲/b'),
            SourceRecord('b', True, 7, False, '甲/b'),
            SourceRecord('b', 1, None, False, '甲/b'),
            SourceRecord('b', 1, 3, True, '甲/b'),
            SourceRecord('b', 1, True, False, '甲/b'),
            SourceRecord('b', 1, 3, False, ' '),
            SourceRecord('b', 1, 3, 0, '甲/b'),
        ]
        valid = self.lake.register('有效卷', [])
        for record in bad_records:
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    self.lake.register('坏形态卷', [value('a', 1, 0, '甲/a'), record])
                with self.assertRaises(KeyError):
                    self.lake.catalog.get_volume(valid + 1)
        replacement = self.lake.register('可装载卷', [value('a', 1, 0, '甲/a')])
        self.assertEqual(replacement, valid + 1)

    def test_request_rebound(self):
        first, second = self.bind([value('a', 1, 8, '甲/a')], [])
        third = self.lake.register('第三卷', [])
        with self.assertRaises(ValueError):
            self.lake.start('day', first, third)
        self.assertEqual(self.lake.requests.get_binding('day').volumes, (first, second))
        self.assertTrue(self.lake.step('day').finished)
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 1, 8, first, 0, '甲/a')])

    def test_swapped_order(self):
        first, second = self.bind([value('a', 2, 7, '甲/a')], [value('a', 2, 9, '乙/a')])
        self.reopen()
        with self.assertRaises(ValueError):
            self.lake.start('day', second, first)
        self.assertEqual(self.lake.start('day', first, second).volumes, (first, second))
        self.lake.step('day')
        self.assertEqual(row_fields(self.lake.read('day')), [('a', 2, 9, second, 0, '乙/a')])

    def test_unknown_volume(self):
        first = self.lake.register('甲卷', [])
        with self.assertRaises(KeyError):
            self.lake.start('day', first, first + 1)
        with self.assertRaises(KeyError):
            self.lake.requests.get_binding('day')
        second = self.lake.register('乙卷', [])
        self.assertEqual(self.lake.start('day', first, second).volumes, (first, second))
