# 热点复扫对照

白班继续按 README.md 登记测温格网。复扫员凭两份固定热图复核热点及原等温臂的热侧，库连接可以关闭。温度、格距、原点、单元行列与半刻度阈值沿用原约定。

## 封存与领取

```python
from archive.pickup import pickup_artifact
from freeze.assemble import freeze_hotspots
from review.report import compare_hotspots

# intake 与 archive 沿用 README 中的存储对象。
# old_revision 与 new_revision 是同批两次扫描的固定修订号。
old_artifact = freeze_hotspots(intake, archive, old_revision, '1/2')
new_artifact = freeze_hotspots(intake, archive, new_revision, '1/2')
old_carrier = pickup_artifact(archive, old_artifact)
new_carrier = pickup_artifact(archive, new_artifact)
# 关闭数据库连接后即可调用。
comparison = compare_hotspots(old_carrier, new_carrier)
```

`freeze_hotspots(intake, archive, revision_id, threshold, *, fail_before_commit=False) -> str` 接收与原封存入口相同的参数，使用指定可加工修订的一份快照。成果共用原目录和领取入口。新版载荷沿用规范 JSON 与正文 SHA-256，正文 `version` 为 `2`，保留原成果字段与原段记录，增加 `batch_id` 及供离线判断热侧的证据。热侧证据的表示由实现定义并说明。新版件可以通过 `inspect_cell` 逐格查看、通过 `audit_contour` 核对原走线，仍按原格式交付。保留原接口、走线报告、历史领取和全部原回归。

停用及更正只影响源侧。停源或重开后可按原成果号领取相同字节。未知或停用修订、非法阈值等沿用原封存异常。`fail_before_commit=True` 沿用 `archive.publish.PublishAborted` 及其中的候选 `artifact_id`，失败后该号无法领取，原结果仍可复领。

## 离线输入及核账规则

`compare_hotspots(old_carrier: bytes, new_carrier: bytes) -> dict` 仅凭两个新版载荷工作。两件须同批、同格网尺寸、同阈值，且修订号不同。参数顺序定义旧版与复扫版，隔代和反向对照均合法。原格网左上角为共同原点，所有格距为一。旧件、不匹配件、格式或者摘要损坏、热侧证据与原格网、交点或原段接法矛盾时抛 `ValueError`。摘要正确的矛盾件也须拒绝。例如对中心相交、四边比例均为 1/2 的四臂证据，只将北边比例改为 1/4 并重算摘要，仍应拒收。

按整幅连续双线性温度面的严格超阈值集合取连通区域。全热格参加连接，全冷格无热区。临界鞍点处，四臂在原等温集合内相接，夹在其中的两个相对热域在该点仍分离。每一原段端口所引向的格内等温臂都有相邻热区。按原段、原端口分别记录其所属的全幅热区，同格双支保留各自出处。区域按全幅实际连通性取号，格外绕接的局部热域可归同一全幅热区。

两版热区只要共同包含至少一个相同坐标的原热样点，就有一条对应。一个旧区有多个后继即拆分，一个新区有多个前驱即合并，无后继即消失，无前驱即新生。保留全部对应。格子重叠、走线接触和相同段身份本身均不产生对应。

## 返回格式

返回由字典、列表、整数和字符串组成，可直接转成 JSON。

- 顶层 `batch_id`、`threshold2`、`cell_shape` 分别是批次、倍增阈值及单元 `[rows, cols]`。
- `old` 和 `new` 各含 `artifact_id`、`revision_id`、`regions`、`port_regions`。`regions` 逐热区列出全部原热样点，每点为零起 `[row, col]`。区内按坐标升序去重，各区按最小坐标升序，区域号为列表零起下标。
- `port_regions` 的外层依新版件原段顺序，每项内层依该段端口顺序，值为对应的本版区域号。无段时为空列表，四臂原段对应一项含四个编号的列表。
- `matches` 是全部 `[旧区号, 新区号]`，按号对升序去重。`splits` 与 `disappeared` 列旧区号，`merges` 与 `born` 列新区号，均升序。无项时返回空列表。

## 小样例

`hotspots_cases.py` 提供同批的旧图与复扫图，均用阈值 `1/2`。可用 `python3 -B hotspots_cases.py` 检查当前走线结果及其证据边界。

- `opposite`。原走线均是一个四臂分量。旧区依次为 `[[[0,0]], [[1,1]]]`，新区依次为 `[[[0,1]], [[1,0]]]`。两版的 `port_regions` 分别为 `[[0,1,1,0]]` 和 `[[0,0,1,1]]`。`matches` 为空，`disappeared` 和 `born` 均为 `[0,1]`。
- `split`。正向 `matches` 为 `[[0,0],[0,1]]`，`splits` 为 `[0]`。交换两件后 `matches` 为 `[[0,0],[1,0]]`，`merges` 为 `[0]`。
- `cross`。两条旧热行各与两条新热列共有角点。`matches` 为 `[[0,0],[0,1],[1,0],[1,1]]`，`splits` 与 `merges` 均为 `[0,1]`。
- `uniform`。两版原段均为空，旧版有一个含四点的热区，复扫无热区。`disappeared` 为 `[0]`。
- `saddle`。热样点位置相同。旧版两个热角可相通，复扫分为两区。`matches` 为 `[[0,0],[0,1]]`。

## 核验和演示

可全量计算并复用原事务。交付时简述热侧证据与原段身份的交接条件。更新现有 `.pointwise-runtime.json` 的核验与演示命令。沿用版本 1、`cli` 类型及现有 `setup` 命令参数列表格式，`verify` 和 `demo` 各用一组命令参数。核验运行全部原回归并检查新版封存到断库对照的业务结果，核验失败返回非零退出码。演示使用真实入口输出停源、重开领取及关库后的热点对照结果。
