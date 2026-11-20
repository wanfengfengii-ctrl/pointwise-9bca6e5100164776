"""Business examples for the North Bank switchover contract."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import check_project
import demo
from lake import Balance, Lake, PublicationRejected, RetryableSource, SourceRecord
from tests.fixture import InterruptedSource, Interruptions, row_fields, value


SAMPLE = Path(__file__).with_name('samples') / 'switchover.json'


def rejects(error, operation):
    try:
        operation()
    except error:
        return
    raise AssertionError(f'expected {error.__name__}')


class Scenario:
    def __init__(self, files):
        self.files = files
        self.events = Interruptions()
        self.reject_commit = False
        self.commit_attempts = []

    def before_switch_commit(self, job_id):
        self.commit_attempts.append(job_id)
        if self.reject_commit:
            self.reject_commit = False
            raise PublicationRejected('switchover commit interrupted')

    def open(self):
        return Lake(*self.files, source_factory=lambda store: InterruptedSource(store, self.events),
                    before_switch_commit=self.before_switch_commit)

    def prepare(self, lake, *, left_version=4, replacement_version=4, empty=False, lost_job='A'):
        data = json.loads(SAMPLE.read_text(encoding='utf-8'))
        data['first']['records'][1]['version'] = left_version
        data['replacement']['records'][0]['version'] = replacement_version
        if empty:
            data['replacement']['records'] = []
            data['replacement']['available'] = 0
        self.first, self.old, self.replacement = (
            lake.register(part['name'], (SourceRecord(**r) for r in part['records']),
                          available=part['available'])
            for part in (data['first'], data['old'], data['replacement'])
        )
        self.binding = lake.start('A', self.first, self.old)
        lake.start('B', self.first, self.old)
        assert lake.step('A').visible_count == 1
        self.prefix = lake.read('A')
        assert row_fields(self.prefix) == [('a', 2, 7, self.first, 0, '甲/a')]
        lake.source.release(self.old, 3)
        offered = lake.source.poll(self.old).slot
        assert offered is not None and offered.position == 2
        self.token = offered.confirmation_id
        self.events.after_confirmation.add(self.token)
        rejects(RetryableSource, lambda: lake.step(lost_job))
        assert lake.read('A') == self.prefix

    def request(self, lake, *, request_id='handover-A', expected_next=3, replacement=None):
        if replacement is None:
            replacement = self.replacement
        return lake.switch_volume('A', request_id, 1, self.old, expected_next, replacement)


def fixture(files):
    case = Scenario(files)
    with case.open() as lake:
        case.prepare(lake)
        before, old_end = lake.journal.read_view('A', case.old)
        assert [(e.slot.position, e.confirmed) for e in before] == [(0, True), (1, True), (2, False)]
        assert old_end is None
        assert lake.source.confirmation_result(case.old, case.token).position == 2
        rejects(ValueError, lambda: lake.start('A', case.first, case.replacement))
    with case.open() as lake:
        lake.source.release(case.old)
        assert lake.step('B').finished
        after, old_end = lake.journal.read_view('A', case.old)
        assert [e.slot.position for e in after] == [0, 1, 2, 3] and old_end == 4
        assert lake.step('A').finished
        assert lake.balance('A') == lake.balance('B') == Balance(2, 57)
        assert row_fields(lake.read('A', case.prefix.next_position)) == [
            ('b', 5, 50, case.old, 3, '乙/b-迟到')]
        return {'V1_shared_slots_before': len(before), 'V1_shared_slots_after': len(after),
                'V1_origin_after': asdict(lake.read('A').rows[-1].origin),
                'V1_balance': asdict(lake.balance('A'))}


def shared_case(files, *, check_errors=False):
    case = Scenario(files)
    with case.open() as lake:
        case.prepare(lake)
        if check_errors:
            backwards = lake.register('逆接卷', [value('a', 8, 99, '逆/a')])
            rejects(ValueError, lambda: case.request(lake, replacement=backwards))
            rejects(ValueError, lambda: case.request(lake, expected_next=2))
            rejects(ValueError, lambda: lake.switch_volume('A', 'closed-side', 0, case.first, 2,
                                                          case.replacement))
            case.reject_commit = True
            rejects(PublicationRejected, lambda: case.request(lake))
            assert case.commit_attempts == ['A']
    with case.open() as lake:
        assert lake.read('A') == case.prefix
        if check_errors:
            case.events.unreadable_receipts.add(case.token)
            try:
                rejects(RetryableSource, lambda: lake.step('A'))
            finally:
                case.events.unreadable_receipts.remove(case.token)
        receipt = case.request(lake)
        attempts = ['A', 'A'] if check_errors else ['A']
        assert case.commit_attempts == attempts
        assert (receipt.job_id, receipt.request_id, receipt.side, receipt.old_volume,
                receipt.old_next, receipt.replacement_volume) == (
                    'A', 'handover-A', 1, case.old, 3, case.replacement)
    with case.open() as lake:
        assert case.request(lake) == receipt
        assert lake.start('A', case.first, case.old) == case.binding
        if check_errors:
            rejects(ValueError, lambda: case.request(lake, expected_next=2))
            rejects(ValueError, lambda: case.request(lake, request_id='again'))
        lake.source.release(case.old)
        assert lake.step('B').finished
        assert lake.source.confirmation_result(case.old, case.token).position == 2
        assert row_fields(lake.read('B')) == [
            ('a', 2, 7, case.first, 0, '甲/a'), ('b', 5, 50, case.old, 3, '乙/b-迟到')]
        assert lake.balance('B') == Balance(2, 57)
        assert not lake.step('A').finished
        paused = lake.read('A', case.prefix.next_position)
        assert (paused.rows, paused.next_position) == ((), case.prefix.next_position)
        lake.source.release(case.replacement)
        assert lake.step('A').finished
    with case.open() as lake:
        tail = lake.read('A', case.prefix.next_position)
        assert row_fields(tail) == [('b', 4, 13, case.replacement, 0, '乙补/b'),
                                    ('c', 1, 2, case.replacement, 1, '乙补/c')]
        assert tail.finished and tail.next_position.offset == 3
        assert lake.read('A').rows == (*case.prefix.rows, *tail.rows)
        assert case.request(lake) == receipt and case.commit_attempts == attempts
        assert lake.balance('A') == Balance(3, 22)
        return {'prefix': [asdict(row) for row in case.prefix.rows],
                'paused_at': asdict(paused.next_position),
                'A': {'tail': [asdict(row) for row in tail.rows], **asdict(lake.balance('A'))},
                'B': {'rows': [asdict(row) for row in lake.read('B').rows],
                      **asdict(lake.balance('B'))}}


def retained_tail_case(files, mode):
    case = Scenario(files)
    empty = mode == 'empty'
    tied = mode == 'same-side-tie'
    with case.open() as lake:
        case.prepare(lake, left_version=2, replacement_version=3 if tied else 2, empty=empty,
                     lost_job='B' if mode == 'lower-version' else 'A')
        if empty:
            rejects(RetryableSource, lambda: case.request(lake))
            lake.source.release(case.replacement)
        elif tied:
            spare = lake.register('空甲卷', [])
            lake.start('pre-capture', spare, case.replacement)
            assert not lake.step('pre-capture').finished
            assert lake.source.poll(case.replacement).position == 1
        case.events.unreadable_receipts.add(case.token)
        case.request(lake)
    with case.open() as lake:
        lake.source.release(case.replacement)
        assert lake.step('A').finished
        if tied:
            winner = ('b', 3, 13, case.replacement, 0, '乙补/b')
        else:
            winner = ('b', 3, 11, case.old, 2, '乙/b-保全')
        rows = [winner]
        if not empty:
            rows.append(('c', 1, 2, case.replacement, 1, '乙补/c'))
        assert row_fields(lake.read('A', case.prefix.next_position)) == rows
        assert lake.balance('A') == Balance(1 + len(rows), 7 + sum(row[2] for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fixture', 'verify', 'demo'))
    mode = parser.parse_args().mode
    if mode == 'verify':
        original_status = check_project.main()
        if original_status:
            return original_status
    if mode == 'demo':
        demo.main()
    with TemporaryDirectory(prefix='north-lake-switch-') as directory:
        def files(case):
            home = Path(directory)
            return home / f'{case}-lake.sqlite', home / f'{case}-source.sqlite'

        if mode == 'fixture':
            report = fixture(files('fixture'))
        else:
            report = shared_case(files('shared'), check_errors=mode == 'verify')
            if mode == 'verify':
                for case in ('lower-version', 'same-side-tie', 'empty'):
                    retained_tail_case(files(case), case)
    print('POINTWISE_SWITCHOVER ' + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
