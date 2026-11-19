# 窑炉热像交班

陶瓷厂白班用设备导出的整数温度表定位可疑热区。夜班在设备源停用后，凭固定成果判断两处标记是否属于同一条等温线。次日复扫形成新修订，旧班次凭据仍能领回当时的报告和成果。

在项目根目录用 Python 3.11 运行。依赖均为标准库。

```sh
python3 -B -m unittest discover -s tests
python3 -B demo.py
```

演示从 `samples/grids.json` 加载四份小热图，在独立临时库完成封存、离线核账、班次确认及重开领取。`POINTWISE_SCENARIO` 行记录实测结果和手算对照。

## 使用流程

以下是白班、夜班和次日复扫的同一条工作流程。三个存储对象可共享一个 `sqlite3.Connection`。也可在另一个连接上重建这些对象。业务写入口管理自己的提交边界，应在无外层事务的连接上调用。

```python
import sqlite3
from contextlib import closing
from fractions import Fraction

from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from freeze.assemble import freeze_contour
from freeze.field_view import inspect_cell
from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from review.report import audit_contour
from handover.register import ack_handover
from handover.history import load_handover
from handover.store import HandoverStore


def open_stores(connection):
    stores = IntakeStore(connection), ArchiveStore(connection), HandoverStore(connection)
    for store in stores:
        store.initialize()
    return stores


with closing(sqlite3.connect('kiln.sqlite3')) as connection:
    intake, archive, handovers = open_stores(connection)
    revision = ingest_grid(intake, 'kiln-7-scan', [[11, 0], [0, 3]])
    artifact = freeze_contour(intake, archive, revision, Fraction(5, 2))
    field_sections = inspect_cell(archive, artifact, (0, 0))
    carrier = pickup_artifact(archive, artifact)

report = audit_contour(carrier)

with closing(sqlite3.connect('kiln.sqlite3')) as connection:
    intake, archive, handovers = open_stores(connection)
    receipt = ack_handover(archive, handovers, 'night-1', report, artifact)
    rescan = ingest_grid(intake, 'kiln-7-scan', [[0, 0], [0, 0]], predecessor=revision)
    disable_source(intake, revision)
    new_artifact = freeze_contour(intake, archive, rescan, '5/2')

with closing(sqlite3.connect('kiln.sqlite3')) as connection:
    intake, archive, handovers = open_stores(connection)
    original_receipt, original_carrier = load_handover(handovers, archive, receipt.receipt_id)
```

1. 设备批次通过 `ingest_grid` 得到固定修订号。复扫可显式指定同批当前前版，也可省略前版，由登记事务解析当时的当前版。
2. `freeze_contour` 读取指定修订的加工资格和温度快照。取源后的加工都使用该快照。
3. 归档提交完整成果后，`inspect_cell` 按成果号和单元返回 `tuple[CellSection, ...]`，供白班标记边位置。
4. `pickup_artifact` 交付固定的离线字节。`archive.catalog.list_artifacts` 按发布顺序列出目录。
5. `audit_contour` 只消费离线字节，返回有序 `AuditReport`。每个分量含原格内段和外缘交点。
6. `ack_handover` 核对报告与申报的已发布成果，返回含 `receipt_id` 及固定清单的凭据。同班次对同一成果重复确认时读回原凭据。
7. 次日登记新修订并按号停用旧加工源。新旧成果各绑定自己的修订。
8. 重开后调用 `load_handover` 取得原凭据和原成果字节。`list_shift_handovers` 按确认顺序列出某班次的凭据。

## 数据和计算约定

- 批次号和班次号是非空文本。热图接受行序列组成的矩形列表或元组，最小为两个顶点行、两个顶点列。顶点温度须为同一刻度的整数。空值、布尔值、浮点值和不等长的行均拒绝。
- 阈值接受 `Fraction` 或可精确解析的字符串，例如 `'5/2'`、`'-0.5'`。值必须是奇数的一半。坐标原点在左上方，x 随列向右、y 随行向下，每格宽高为一。单元用 `(row, col)` 定位。
- 每格按四角做双线性插值。边的两个端点分处阈值两侧时有一个交点。`Crossing.offset` 从规范边锚点沿水平方向向东或沿垂直方向向南计量，`Crossing.point` 给出全图 `(x, y)`，均为 `Fraction`。
- 一个格内段可能有两个或四个边交点。格内双支分别保留出处。跨格只沿实际共享边上的同一交点接续。段按行列、北东南西边序和沿边位置排序，分量按最先的段出处排序。没有外缘交点的闭环仍会出现在报告里。有效空格和空图分别返回空的段元组和空的分量元组。
- 离线载荷是 UTF-8 兼容的规范 JSON 字节。正文含版本、成果号、修订号、顶点格网对应的单元行列数、倍增阈值和稀疏段表。交点以规范边和约分的沿边比例保存。归档和离线报告均校验 SHA-256 正文摘要，离线报告还校验内部边的入射关系。

## 失败和历史

非法格网、无效前版、未知编号、越界查询、停用源取件加工、非法阈值、损坏载荷和报告绑定不一致均抛出 `ValueError`。`freeze_contour(..., fail_before_commit=True)` 在插入候选记录后、提交前抛出 `PublishAborted`。该异常的 `artifact_id` 可用于核对候选号无法领取。发布失败不改变已有成果或班次记录。底层数据库操作失败时保留 `sqlite3` 的异常类型。

各存储的 `initialize()` 可重复执行，保留已有修订、当前指针、停用标记、成果和班次凭据。样例仅由演示显式接纳。修订更正与停用发生在源侧，历史领取使用归档与交班记录。
