# 北汊观测湖退役卷日账

北汊观测资料中心把两份退役观测卷归并为一份日账。白班登记上游原件并固定来源卷序。夜班推进回收和归并。资料员在尾部等待时领取已经齐备的前缀，交班后续领，完卷后核对读数和原出处。

## 运行

需要 Python 3.11 和标准库中的 SQLite。在项目根目录运行。

```console
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 由控制台在物化工程时提供，执行 `tests` 包中的完整回归。演示在独立临时目录创建两库，读入 `samples/day.json`，按普通接口登记并推进，再用保存的领取位置重开续领。甲卷 a 的版本较高，先发布 7。两卷的 b 同版本，绑定中靠后的乙卷取 13。c 的最高版本是删除项。完卷为两行、合计 20。演示会核对实际结果后打印本次读取和日账。

## 公开接口

```python
from lake import Lake, SourceRecord

with Lake('day.sqlite', 'retired.sqlite') as lake:
    left = lake.register('甲卷', [SourceRecord('a', 2, 7, False, '甲站/a')])
    right = lake.register('乙卷', [SourceRecord('a', 1, 5, False, '乙站/a')])
    binding = lake.start('北汊日批', left, right)
    state = lake.step(binding.job_id)
    page = lake.read(binding.job_id)
    totals = lake.balance(binding.job_id)
```

- `register(name, records)` 返回卷登记号。`SourceRecord` 参数依次为键、版本、读值、删除标志、原出处标识。键和出处使用非空字符串。卷内键按区分大小写的 Python 字符串字典序非降序排列，连续同键合法。版本与读值为整数，读值沿用上游刻度，零和负值有效。删除使用 `deleted=True, value=None`，普通项须有整数值。非法形态及原始键逆序抛出 `ValueError`，整卷拒绝。
- `start(job_id, first, second)` 按顺序绑定两个不同卷号，返回持久 `JobBinding`。同号同序复用。同号改卷或反转顺序抛出 `ValueError`，未知卷抛出 `KeyError`。已经登记的卷如被多个归并引用，只回收一次，完整原件由湖库保存，各归并独立裁决和领取。
- `step(job_id)` 接管当前可交付的槽位，返回 `StepResult`，其中 `visible_count` 为已提交明细数，`finished` 表示完卷。未知归并抛出 `KeyError`。`RetryableSource` 表示源确认需续办，`PublicationRejected` 表示本次发布可重试。失败时保留调用前已经固定的领取成果以及已成功写入的接管事实。
- `read(job_id, position=None)` 从起点或保存的 `ReadPosition(job_id, offset)` 取得其后已发布的 `rows`、`next_position` 和 `finished`。每行附原卷登记号、从零开始的原位置和原出处标识。位置按可见行计数，空页保持原位置。未知归并抛出 `KeyError`，异归并位置或越界抛出 `ValueError`。
- `balance(job_id)` 尚未完卷返回 `None`，完卷返回 `Balance(row_count, total)`。每一条固定明细都参与计数及求和，多个键相同的读值分别入账。空结果为 `Balance(0, 0)`。

## 退役卷换卷

- `switch_volume(job_id, request_id, side, expected_old_volume, expected_next, replacement_volume)` 为未完卷日批的一侧（`side` 为 0 或 1）申请单次换卷，返回不可变 `SwitchReceipt`。它核对原卷自物理零槽起在湖库连续保全的槽数（`expected_next` 即排他截点，0 表示尚无保全槽），截点内原件继续参选；补卷须可读物理零槽或正式空卷尾，暂缺抛 `RetryableSource`，且补卷首键不得低于保留尾键。切换与首执在同一事务提交，`before_switch_commit` 抛 `PublicationRejected` 时整体回滚。同号同参重开重领原首执，异参、过时截点或二次换卷抛 `ValueError`。换卷后 `step`、`read`、`balance` 接口不变：旧确认仍按原物理卷与确认号查询，胜项交付实际物理卷号、零基槽位和原出处，领取游标与已发布明细保持不变。业务细则见 `SWITCHOVER.md`，核验与演示见 `python3 -B switch_examples.py verify` 和 `python3 -B switch_examples.py demo`。

登记时可用 `available=整数` 提供初始可见槽数，并保留正式卷尾。供件方通过 `lake.source.release(volume_id, count)` 增加可用槽数，通过 `lake.source.release(volume_id)` 放开剩余槽和正式卷尾。供件进度随同源库重开恢复。正常登记默认开放所有槽和卷尾。一次归并只推进所绑定的两卷。

## 推进与重开

1. 目录校验整卷，再装载源库原槽，装载后激活登记号。绑定冻结按版本、绑定卷序、卷内原位置从大到小决胜的规程。
2. 源库一次交出一个待确认槽。接管把版本、读值或删除形态、原出处和原确认号一并保存。源确认在一项事务内回收原件并保存可查询的收据。
3. 确认回包中断时，接管重查原号。已生效的结局与湖库原件配对。确认尚未生效时以原号重试。
4. 两卷分别以连续接管的严格更大键或正式卷尾证明一个键已齐备。暂缺和相等键维持等待。已齐备前缀立即裁决。读值胜项追加固定明细，删除胜项只提交内部裁决。前缀、领取上界和完卷标志共同提交。
5. 重开时使用原湖库和原源库。初始化只补齐结构，保留用户登记、在途接管、固定明细和旧领取位置。完卷核账逐行读取相同的固定明细，使用 Python 整数精确求和。
