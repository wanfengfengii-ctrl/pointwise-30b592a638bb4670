import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass

from freeze.cell_topology import classify_cell
from freeze.edge_crossings import crossing_from_record, crossing_to_record, grid_edge
from freeze.evidence import (
    EDGE_ORDER,
    CellSection,
    ContourEvidence,
    HotspotEvidence,
    section_sort_key,
)


@dataclass(frozen=True)
class ArtifactPayload:
    artifact_id: str
    evidence: ContourEvidence


_V1_BODY_KEYS = {'version', 'artifact_id', 'revision_id', 'threshold2', 'rows', 'cols', 'sections'}
_V2_BODY_KEYS = _V1_BODY_KEYS | {'batch_id', 'vertices'}


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False
    ).encode('ascii')


def encode_artifact(payload: ArtifactPayload) -> bytes:
    evidence = payload.evidence
    hotspot = isinstance(evidence, HotspotEvidence)
    body = {
        'version': 2 if hotspot else 1,
        'artifact_id': payload.artifact_id,
        'revision_id': evidence.revision_id,
        'threshold2': evidence.threshold2,
        'rows': evidence.rows,
        'cols': evidence.cols,
        'sections': [
            {
                'cell': [section.row, section.col],
                'ports': [[side, crossing_to_record(crossing)] for side, crossing in section.ports],
            }
            for section in evidence.sections
        ],
    }
    if hotspot:
        body['batch_id'] = evidence.batch_id
        body['vertices'] = [list(row) for row in evidence.vertices]
    return canonical_json({'body': body, 'sha256': hashlib.sha256(canonical_json(body)).hexdigest()})


def _read_section(record: object, rows: int, cols: int) -> CellSection:
    if not isinstance(record, dict) or record.keys() != {'cell', 'ports'}:
        raise ValueError('invalid section record')
    cell = record['cell']
    if not isinstance(cell, list) or len(cell) != 2 or any(type(value) is not int for value in cell):
        raise ValueError('invalid section cell')
    row, col = cell
    if not (0 <= row < rows and 0 <= col < cols):
        raise ValueError('section lies outside the grid')

    ports = []
    entries = record['ports']
    if not isinstance(entries, list) or len(entries) not in (2, 4):
        raise ValueError('section requires two or four crossings')
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 2 or entry[0] not in EDGE_ORDER:
            raise ValueError('invalid section port')
        side, raw_crossing = entry
        crossing = crossing_from_record(raw_crossing)
        if crossing.edge != grid_edge(row, col, side):
            raise ValueError('port does not lie on the stated cell side')
        ports.append((side, crossing))
    sides = tuple(side for side, _ in ports)
    if sides != tuple(side for side in EDGE_ORDER if side in sides):
        raise ValueError('section sides must be unique and ordered')
    return CellSection(row, col, tuple(ports))


def _read_sections(entries: object, rows: int, cols: int) -> tuple[CellSection, ...]:
    if not isinstance(entries, list):
        raise ValueError('invalid section table')
    sections = tuple(_read_section(entry, rows, cols) for entry in entries)
    if sections != tuple(sorted(sections, key=section_sort_key)):
        raise ValueError('sections are out of order')

    groups_by_cell = defaultdict(list)
    for section in sections:
        groups_by_cell[section.row, section.col].append(section.sides)
    for groups in groups_by_cell.values():
        if len(groups) == 1:
            continue
        if tuple(groups) not in ((('N', 'W'), ('E', 'S')), (('N', 'E'), ('S', 'W'))):
            raise ValueError('invalid partition of cell crossings')
    return sections


def _read_common_body(body: dict) -> tuple:
    artifact_id, revision_id = body['artifact_id'], body['revision_id']
    if any(not isinstance(value, str) or not value for value in (artifact_id, revision_id)):
        raise ValueError('invalid artifact identity')
    rows, cols = body['rows'], body['cols']
    if any(type(value) is not int or value < 1 for value in (rows, cols)):
        raise ValueError('invalid artifact dimensions')
    threshold2 = body['threshold2']
    if type(threshold2) is not int or threshold2 % 2 != 1:
        raise ValueError('invalid artifact threshold')
    sections = _read_sections(body['sections'], rows, cols)
    return artifact_id, revision_id, rows, cols, threshold2, sections


def _read_vertices(raw: object, rows: int, cols: int) -> tuple[tuple[int, ...], ...]:
    if not isinstance(raw, list) or len(raw) != rows + 1:
        raise ValueError('invalid hotspot evidence grid')
    vertices = []
    for entry in raw:
        if not isinstance(entry, list) or len(entry) != cols + 1:
            raise ValueError('invalid hotspot evidence grid')
        if any(type(temperature) is not int for temperature in entry):
            raise ValueError('hotspot evidence temperatures must be integers')
        vertices.append(tuple(entry))
    return tuple(vertices)


def _check_hotspot_consistency(
    vertices: tuple[tuple[int, ...], ...],
    threshold2: int,
    rows: int,
    cols: int,
    sections: tuple[CellSection, ...],
) -> None:
    expected = []
    for row in range(rows):
        for col in range(cols):
            corners = (
                vertices[row][col],
                vertices[row][col + 1],
                vertices[row + 1][col],
                vertices[row + 1][col + 1],
            )
            expected.extend(classify_cell(row, col, corners, threshold2))
    if tuple(expected) != sections:
        raise ValueError('hotspot evidence contradicts the contour sections')


def decode_artifact(carrier: bytes) -> ArtifactPayload:
    if not isinstance(carrier, bytes):
        raise ValueError('artifact must be bytes')
    try:
        envelope = json.loads(carrier)
        normalized = canonical_json(envelope)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid artifact JSON') from error
    if not isinstance(envelope, dict) or envelope.keys() != {'body', 'sha256'}:
        raise ValueError('invalid artifact envelope')
    if normalized != carrier:
        raise ValueError('artifact encoding is not canonical')
    body = envelope['body']
    if hashlib.sha256(canonical_json(body)).hexdigest() != envelope['sha256']:
        raise ValueError('artifact checksum mismatch')
    if not isinstance(body, dict):
        raise ValueError('invalid artifact body')
    version = body.get('version')
    if type(version) is not int or version not in (1, 2):
        raise ValueError('unsupported artifact version')
    if body.keys() != (_V1_BODY_KEYS if version == 1 else _V2_BODY_KEYS):
        raise ValueError('invalid artifact body')

    artifact_id, revision_id, rows, cols, threshold2, sections = _read_common_body(body)
    if version == 1:
        evidence = ContourEvidence(revision_id, threshold2, rows, cols, sections)
        return ArtifactPayload(artifact_id, evidence)

    batch_id = body['batch_id']
    if not isinstance(batch_id, str) or not batch_id:
        raise ValueError('invalid artifact batch')
    vertices = _read_vertices(body['vertices'], rows, cols)
    _check_hotspot_consistency(vertices, threshold2, rows, cols, sections)
    evidence = HotspotEvidence(
        revision_id=revision_id,
        threshold2=threshold2,
        rows=rows,
        cols=cols,
        sections=sections,
        batch_id=batch_id,
        vertices=vertices,
    )
    return ArtifactPayload(artifact_id, evidence)
