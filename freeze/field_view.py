from archive.codec import decode_artifact
from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from freeze.evidence import CellSection


def inspect_cell(
    archive: ArchiveStore, artifact_id: str, cell: tuple[int, int] | list[int]
) -> tuple[CellSection, ...]:
    if not isinstance(cell, (tuple, list)) or len(cell) != 2:
        raise ValueError('cell must be a row and column pair')
    row, col = cell
    if type(row) is not int or type(col) is not int:
        raise ValueError('cell coordinates must be integers')
    evidence = decode_artifact(pickup_artifact(archive, artifact_id)).evidence
    if not (0 <= row < evidence.rows and 0 <= col < evidence.cols):
        raise ValueError('cell is outside the artifact')
    return tuple(section for section in evidence.sections if (section.row, section.col) == (row, col))
