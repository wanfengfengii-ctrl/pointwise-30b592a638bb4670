from collections import deque
from dataclasses import dataclass

from freeze.edge_crossings import Crossing
from freeze.evidence import EDGE_ORDER
from review.ports import SectionRef
from review.stitch import SectionGraph


@dataclass(frozen=True)
class WalkComponent:
    sections: tuple[SectionRef, ...]
    boundary: tuple[Crossing, ...]


def collect_components(graph: SectionGraph) -> tuple[WalkComponent, ...]:
    seen = set()
    components = []
    for start in sorted(graph.neighbors, key=SectionRef.sort_key):
        if start in seen:
            continue
        pending = deque([start])
        seen.add(start)
        sections = []
        exits = []
        while pending:
            section = pending.popleft()
            sections.append(section)
            for side, crossing in graph.boundary.get(section, ()):
                key = (section.row, section.col, EDGE_ORDER.index(side), crossing.offset)
                exits.append((key, crossing))
            fresh = graph.neighbors[section] - seen
            pending.extend(fresh)
            seen.update(fresh)
        components.append(WalkComponent(
            tuple(sorted(sections, key=SectionRef.sort_key)),
            tuple(crossing for _, crossing in sorted(exits, key=lambda entry: entry[0])),
        ))
    return tuple(components)
