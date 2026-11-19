from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, order=True)
class EdgeId:
    axis: str
    row: int
    col: int


@dataclass(frozen=True)
class Crossing:
    edge: EdgeId
    offset: Fraction

    @property
    def point(self) -> tuple[Fraction, Fraction]:
        x, y = Fraction(self.edge.col), Fraction(self.edge.row)
        if self.edge.axis == 'H':
            return x + self.offset, y
        return x, y + self.offset


def grid_edge(row: int, col: int, side: str) -> EdgeId:
    axis, row_step, col_step = {
        'N': ('H', 0, 0),
        'E': ('V', 0, 1),
        'S': ('H', 1, 0),
        'W': ('V', 0, 0),
    }[side]
    return EdgeId(axis, row + row_step, col + col_step)


def edge_crossings(
    row: int, col: int, corners: tuple[int, int, int, int], threshold2: int
) -> dict[str, Crossing]:
    nw, ne, sw, se = corners
    endpoints = (('N', nw, ne), ('E', ne, se), ('S', sw, se), ('W', nw, sw))
    crossings = {}
    for side, start, end in endpoints:
        if (2 * start < threshold2) != (2 * end < threshold2):
            offset = Fraction(threshold2 - 2 * start, 2 * (end - start))
            crossings[side] = Crossing(grid_edge(row, col, side), offset)
    return crossings


def crossing_to_record(crossing: Crossing) -> list:
    edge = crossing.edge
    offset = crossing.offset
    return [[edge.axis, edge.row, edge.col], [offset.numerator, offset.denominator]]


def crossing_from_record(record: object) -> Crossing:
    if not isinstance(record, list) or len(record) != 2:
        raise ValueError('invalid crossing record')
    anchor, ratio = record
    if not isinstance(anchor, list) or len(anchor) != 3:
        raise ValueError('invalid edge anchor')
    axis, row, col = anchor
    if axis not in ('H', 'V') or any(type(value) is not int or value < 0 for value in (row, col)):
        raise ValueError('invalid edge anchor')
    if not isinstance(ratio, list) or len(ratio) != 2:
        raise ValueError('invalid crossing offset')
    numerator, denominator = ratio
    if type(numerator) is not int or type(denominator) is not int:
        raise ValueError('crossing offset requires integers')
    if not 0 < numerator < denominator:
        raise ValueError('crossing must be strictly inside the edge')
    offset = Fraction(numerator, denominator)
    if (offset.numerator, offset.denominator) != (numerator, denominator):
        raise ValueError('crossing offset must be reduced')
    return Crossing(EdgeId(axis, row, col), offset)
