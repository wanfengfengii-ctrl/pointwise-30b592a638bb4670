from dataclasses import dataclass

from archive.codec import decode_artifact
from freeze.edge_crossings import crossing_from_record, crossing_to_record
from freeze.evidence import EDGE_ORDER
from review.components import WalkComponent, collect_components
from review.ports import SectionRef, index_ports
from review.stitch import stitch_sections


@dataclass(frozen=True)
class AuditReport:
    artifact_id: str
    revision_id: str
    threshold2: int
    components: tuple[WalkComponent, ...]


def audit_contour(carrier: bytes) -> AuditReport:
    payload = decode_artifact(carrier)
    evidence = payload.evidence
    graph = stitch_sections(index_ports(evidence))
    return AuditReport(
        payload.artifact_id, evidence.revision_id, evidence.threshold2, collect_components(graph)
    )


def report_to_record(report: AuditReport) -> dict:
    return {
        'artifact_id': report.artifact_id,
        'revision_id': report.revision_id,
        'threshold2': report.threshold2,
        'components': [
            {
                'sections': [[ref.row, ref.col, list(ref.sides)] for ref in component.sections],
                'boundary': [crossing_to_record(crossing) for crossing in component.boundary],
            }
            for component in report.components
        ],
    }


def _section_ref(record: object) -> SectionRef:
    if not isinstance(record, list) or len(record) != 3:
        raise ValueError('invalid report section')
    row, col, sides = record
    if any(type(value) is not int or value < 0 for value in (row, col)):
        raise ValueError('invalid report cell')
    if not isinstance(sides, list) or len(sides) not in (2, 4):
        raise ValueError('invalid report section sides')
    if sides != [side for side in EDGE_ORDER if side in sides]:
        raise ValueError('report sides must be unique and ordered')
    return SectionRef(row, col, tuple(sides))


def _read_component(record: object) -> WalkComponent:
    if not isinstance(record, dict) or record.keys() != {'sections', 'boundary'}:
        raise ValueError('invalid report component')
    sections, boundary = record['sections'], record['boundary']
    if not isinstance(sections, list) or not sections or not isinstance(boundary, list):
        raise ValueError('invalid report component data')
    refs = tuple(_section_ref(section) for section in sections)
    if refs != tuple(sorted(set(refs), key=SectionRef.sort_key)):
        raise ValueError('report sections must be unique and ordered')
    return WalkComponent(refs, tuple(crossing_from_record(entry) for entry in boundary))


def report_from_record(record: object) -> AuditReport:
    if not isinstance(record, dict) or record.keys() != {
        'artifact_id', 'revision_id', 'threshold2', 'components'
    }:
        raise ValueError('invalid report record')
    artifact_id, revision_id = record['artifact_id'], record['revision_id']
    if any(not isinstance(value, str) or not value for value in (artifact_id, revision_id)):
        raise ValueError('invalid report identity')
    threshold2 = record['threshold2']
    if type(threshold2) is not int or threshold2 % 2 != 1:
        raise ValueError('invalid report threshold')
    entries = record['components']
    if not isinstance(entries, list):
        raise ValueError('invalid report component list')

    components = tuple(_read_component(entry) for entry in entries)
    refs = [ref for component in components for ref in component.sections]
    if len(refs) != len(set(refs)):
        raise ValueError('a report section occurs in multiple components')
    if components != tuple(sorted(components, key=lambda item: item.sections[0].sort_key())):
        raise ValueError('report components are out of order')
    return AuditReport(artifact_id, revision_id, threshold2, components)
