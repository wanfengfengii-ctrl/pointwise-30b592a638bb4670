from collections import defaultdict
from dataclasses import dataclass

from freeze.edge_crossings import Crossing, EdgeId
from freeze.evidence import EDGE_ORDER, ContourEvidence


@dataclass(frozen=True)
class SectionRef:
    row: int
    col: int
    sides: tuple[str, ...]

    def sort_key(self) -> tuple:
        return self.row, self.col, tuple(EDGE_ORDER.index(side) for side in self.sides)


@dataclass(frozen=True)
class PortIndex:
    sections: tuple[SectionRef, ...]
    internal_pairs: tuple[tuple[SectionRef, SectionRef], ...]
    boundary: dict[SectionRef, tuple[tuple[str, Crossing], ...]]


@dataclass(frozen=True)
class _Incidence:
    section: SectionRef
    side: str
    crossing: Crossing

    @property
    def cell(self) -> tuple[int, int]:
        return self.section.row, self.section.col


def _incident_cells(edge: EdgeId, rows: int, cols: int) -> set[tuple[int, int]]:
    row, col = edge.row, edge.col
    if edge.axis == 'H':
        neighbors = ((row - 1, col), (row, col))
    else:
        neighbors = ((row, col - 1), (row, col))
    return {(r, c) for r, c in neighbors if 0 <= r < rows and 0 <= c < cols}


def index_ports(evidence: ContourEvidence) -> PortIndex:
    refs = []
    by_edge = defaultdict(list)
    for section in evidence.sections:
        ref = SectionRef(section.row, section.col, section.sides)
        refs.append(ref)
        for side, crossing in section.ports:
            by_edge[crossing.edge].append(_Incidence(ref, side, crossing))

    internal_pairs = []
    boundary = defaultdict(list)
    for edge, incidences in by_edge.items():
        expected = _incident_cells(edge, evidence.rows, evidence.cols)
        cells = {incidence.cell for incidence in incidences}
        if cells != expected or len(incidences) != len(expected):
            raise ValueError('edge crossings do not have the required incident cells')
        first = incidences[0]
        if len(incidences) == 1:
            boundary[first.section].append((first.side, first.crossing))
        else:
            second = incidences[1]
            if first.crossing != second.crossing:
                raise ValueError('shared edge has inconsistent crossing positions')
            internal_pairs.append((first.section, second.section))

    return PortIndex(tuple(refs), tuple(internal_pairs), {
        ref: tuple(ports) for ref, ports in boundary.items()
    })
