"""仅凭新版封存字节计算全幅热区并对照两版复扫热点。"""
from dataclasses import dataclass

from archive.codec import ArtifactPayload, decode_artifact
from freeze.evidence import HotspotEvidence

# 单元角点编号：0=NW、1=NE、2=SW、3=SE。
_CORNER_OFFSET = ((0, 0), (0, 1), (1, 0), (1, 1))
_SIDE_CORNERS = {'N': (0, 1), 'E': (1, 3), 'S': (2, 3), 'W': (0, 2)}


@dataclass(frozen=True)
class HotRegions:
    """一版封存件的全幅热区：逐区有序热样点及逐原段端口的热区号。"""

    regions: tuple[tuple[tuple[int, int], ...], ...]
    port_regions: tuple[tuple[int, ...], ...]


class _UnionFind:
    def __init__(self) -> None:
        self._parent = {}

    def add(self, node: tuple) -> None:
        self._parent.setdefault(node, node)

    def find(self, node: tuple) -> tuple:
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, first: tuple, second: tuple) -> None:
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            self._parent[second_root] = first_root


def _cell_zones(corners: tuple[int, int, int, int], threshold2: int) -> tuple[frozenset, ...]:
    """按格内双线性面的严格超阈值集合给出热域各自连通的角点。

    全冷格无热域，全热格整格连通。对角双热格在鞍点严格为热时连通；
    临界鞍点（行列式为零）上四臂在原等温集合内相接，但两侧相对热域保持分离。
    """
    hot = tuple(
        index for index, temperature in enumerate(corners) if 2 * temperature > threshold2
    )
    if len(hot) == 0:
        return ()
    if len(hot) != 2 or hot[0] + hot[1] != 3:
        return (frozenset(hot),)
    values = [2 * temperature - threshold2 for temperature in corners]
    determinant = values[0] * values[3] - values[1] * values[2]
    if determinant > 0:
        return (frozenset(hot),)
    return frozenset((hot[0],)), frozenset((hot[1],))


def compute_hot_regions(evidence: HotspotEvidence) -> HotRegions:
    """按全幅连续双线性面的严格超阈值集合取连通区域，并对应到原段端口。"""
    vertices, threshold2 = evidence.vertices, evidence.threshold2
    rows, cols = evidence.rows, evidence.cols

    def is_hot(row: int, col: int) -> bool:
        return 2 * vertices[row][col] > threshold2

    union_find = _UnionFind()
    zone_of_corner = {}
    for row in range(rows):
        for col in range(cols):
            corners = (
                vertices[row][col],
                vertices[row][col + 1],
                vertices[row + 1][col],
                vertices[row + 1][col + 1],
            )
            mapping = {}
            for index, zone in enumerate(_cell_zones(corners, threshold2)):
                node = (row, col, index)
                union_find.add(node)
                for corner in zone:
                    mapping[corner] = node
            zone_of_corner[row, col] = mapping

    # 相邻格的热域沿有热端点的共享边相接；格外绕接的局部热域并入同一全幅热区。
    for row in range(rows):
        for col in range(1, cols):
            if is_hot(row, col) or is_hot(row + 1, col):
                west = 1 if is_hot(row, col) else 3
                east = 0 if is_hot(row, col) else 2
                union_find.union(
                    zone_of_corner[row, col - 1][west], zone_of_corner[row, col][east]
                )
    for row in range(1, rows):
        for col in range(cols):
            if is_hot(row, col) or is_hot(row, col + 1):
                north = 2 if is_hot(row, col) else 3
                south = 0 if is_hot(row, col) else 1
                union_find.union(
                    zone_of_corner[row - 1, col][north], zone_of_corner[row, col][south]
                )

    points_by_root = {}
    for row in range(rows + 1):
        for col in range(cols + 1):
            if not is_hot(row, col):
                continue
            cell_row, cell_col = min(row, rows - 1), min(col, cols - 1)
            corner = 2 * (row > cell_row) + (col > cell_col)
            root = union_find.find(zone_of_corner[cell_row, cell_col][corner])
            points_by_root.setdefault(root, set()).add((row, col))

    ordered = sorted(points_by_root.items(), key=lambda item: min(item[1]))
    region_of_root = {root: index for index, (root, _) in enumerate(ordered)}
    regions = tuple(tuple(sorted(points)) for _, points in ordered)

    port_regions = []
    for section in evidence.sections:
        entry = []
        for side, _crossing in section.ports:
            for corner in _SIDE_CORNERS[side]:
                d_row, d_col = _CORNER_OFFSET[corner]
                if is_hot(section.row + d_row, section.col + d_col):
                    node = zone_of_corner[section.row, section.col][corner]
                    entry.append(region_of_root[union_find.find(node)])
                    break
            else:
                raise ValueError('section port has no hot endpoint')
        port_regions.append(tuple(entry))
    return HotRegions(regions, tuple(port_regions))


def _decode_hotspot_payload(carrier: bytes) -> ArtifactPayload:
    payload = decode_artifact(carrier)
    if not isinstance(payload.evidence, HotspotEvidence):
        raise ValueError('hotspot comparison requires version 2 artifacts')
    return payload


def _version_record(payload: ArtifactPayload, hot: HotRegions) -> dict:
    return {
        'artifact_id': payload.artifact_id,
        'revision_id': payload.evidence.revision_id,
        'regions': [[[row, col] for row, col in region] for region in hot.regions],
        'port_regions': [list(entry) for entry in hot.port_regions],
    }


def compare_hotspots(old_carrier: bytes, new_carrier: bytes) -> dict:
    """仅凭两份新版封存字节对照同批、同格网、同阈值的不同修订热点。"""
    old = _decode_hotspot_payload(old_carrier)
    new = _decode_hotspot_payload(new_carrier)
    old_evidence, new_evidence = old.evidence, new.evidence
    if old_evidence.batch_id != new_evidence.batch_id:
        raise ValueError('artifacts do not belong to the same batch')
    if (old_evidence.rows, old_evidence.cols) != (new_evidence.rows, new_evidence.cols):
        raise ValueError('artifacts do not share the grid shape')
    if old_evidence.threshold2 != new_evidence.threshold2:
        raise ValueError('artifacts do not share the threshold')
    if old_evidence.revision_id == new_evidence.revision_id:
        raise ValueError('artifacts must come from different revisions')

    old_hot = compute_hot_regions(old_evidence)
    new_hot = compute_hot_regions(new_evidence)
    old_points = [set(region) for region in old_hot.regions]
    new_points = [set(region) for region in new_hot.regions]
    matches = sorted(
        (old_index, new_index)
        for old_index, old_region in enumerate(old_points)
        for new_index, new_region in enumerate(new_points)
        if old_region & new_region
    )
    successors = {}
    predecessors = {}
    for old_index, new_index in matches:
        successors.setdefault(old_index, set()).add(new_index)
        predecessors.setdefault(new_index, set()).add(old_index)
    return {
        'batch_id': old_evidence.batch_id,
        'threshold2': old_evidence.threshold2,
        'cell_shape': [old_evidence.rows, old_evidence.cols],
        'old': _version_record(old, old_hot),
        'new': _version_record(new, new_hot),
        'matches': [[old_index, new_index] for old_index, new_index in matches],
        'splits': sorted(index for index, followers in successors.items() if len(followers) > 1),
        'merges': sorted(index for index, sources in predecessors.items() if len(sources) > 1),
        'disappeared': sorted(
            index for index in range(len(old_points)) if index not in successors
        ),
        'born': sorted(index for index in range(len(new_points)) if index not in predecessors),
    }
