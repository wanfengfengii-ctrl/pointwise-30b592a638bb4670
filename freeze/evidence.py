from dataclasses import dataclass
from fractions import Fraction

from freeze.edge_crossings import Crossing


EDGE_ORDER = ('N', 'E', 'S', 'W')


@dataclass(frozen=True)
class CellSection:
    row: int
    col: int
    ports: tuple[tuple[str, Crossing], ...]

    @property
    def sides(self) -> tuple[str, ...]:
        return tuple(side for side, _ in self.ports)


@dataclass(frozen=True)
class ContourEvidence:
    revision_id: str
    threshold2: int
    rows: int
    cols: int
    sections: tuple[CellSection, ...]


def parse_half_threshold(raw: object) -> int:
    if not isinstance(raw, (Fraction, str)):
        raise ValueError('threshold must be an exact half-step')
    try:
        threshold = Fraction(raw)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('invalid threshold') from error
    if threshold.denominator != 2:
        raise ValueError('threshold must be an odd multiple of one half')
    return threshold.numerator


def section_sort_key(section: CellSection) -> tuple:
    return (
        section.row,
        section.col,
        tuple(EDGE_ORDER.index(side) for side in section.sides),
        tuple(crossing.offset for _, crossing in section.ports),
    )
