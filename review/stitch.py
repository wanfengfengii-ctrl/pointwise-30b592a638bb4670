from dataclasses import dataclass

from freeze.edge_crossings import Crossing
from review.ports import PortIndex, SectionRef


@dataclass(frozen=True)
class SectionGraph:
    neighbors: dict[SectionRef, frozenset[SectionRef]]
    boundary: dict[SectionRef, tuple[tuple[str, Crossing], ...]]


def stitch_sections(ports: PortIndex) -> SectionGraph:
    neighbors = {section: set() for section in ports.sections}
    for first, second in ports.internal_pairs:
        neighbors[first].add(second)
        neighbors[second].add(first)
    return SectionGraph(
        {section: frozenset(linked) for section, linked in neighbors.items()}, ports.boundary
    )
