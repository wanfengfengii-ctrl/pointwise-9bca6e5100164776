from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from lake import Balance, Lake, ReadPosition, SourceRecord
from lake.audit.provenance import AuditOrigin
from lake.audit.read import ReadRow


def main():
    sample_path = Path(__file__).resolve().parent / 'samples' / 'day.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    job_id = sample['job_id']
    with TemporaryDirectory(prefix='north-lake-demo-') as workspace:
        root = Path(workspace)
        files = root / 'lake.sqlite', root / 'source.sqlite'
        with Lake(*files) as lake:
            volume_ids = []
            for side in ('first', 'second'):
                volume = sample[side]
                volume_ids.append(lake.register(volume['name'],
                                                [SourceRecord(**row) for row in volume['records']],
                                                available=volume['available']))
            first, second = volume_ids
            binding = lake.start(job_id, first, second)
            assert lake.start(job_id, first, second) == binding
            state = lake.step(job_id)
            prefix = lake.read(job_id)
            expected_prefix = ReadRow('a', 2, 7, AuditOrigin(first, 0, '甲站/a'))
            assert prefix.rows == (expected_prefix,)
            assert prefix.next_position == ReadPosition(job_id, 1)
            assert (state.visible_count, state.finished) == (1, False)
            assert lake.balance(job_id) is None
            lake.source.release(first)
            lake.source.release(second)
            state = lake.step(job_id)
            assert (state.visible_count, state.finished) == (2, True)

        with Lake(*files) as lake:
            tail = lake.read(job_id, prefix.next_position)
            totals = lake.balance(job_id)
            expected_tail = ReadRow('b', 2, 13, AuditOrigin(second, 1, '乙站/b'))
            assert tail.rows == (expected_tail,)
            assert tail.next_position == ReadPosition(job_id, 2)
            assert lake.read(job_id).rows == (*prefix.rows, *tail.rows)
            assert totals == Balance(2, 20)

        report = {
            'case_id': 'v5',
            'input': sample,
            'expected': [asdict(expected_prefix)],
            'actual': [asdict(row) for row in prefix.rows],
            'downstream_expected': {'rows': [asdict(expected_tail)], 'row_count': 2, 'total': 20},
            'downstream_actual': {'rows': [asdict(row) for row in tail.rows], **asdict(totals)},
            'code_paths': ['lake/intake/frontier.py', 'lake/merge/plan.py', 'lake/merge/publish.py',
                           'lake/audit/read.py', 'lake/audit/totals.py'],
            'oracle': '手算 a 取甲卷版本 2，b 同版本取乙卷，c 被乙卷删除。7 加 13 得 20。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
