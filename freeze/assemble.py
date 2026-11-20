from archive.publish import publish_artifact
from archive.storage import ArchiveStore
from freeze.cell_topology import classify_cell
from freeze.evidence import (
    CellSection,
    ContourEvidence,
    HotspotEvidence,
    parse_half_threshold,
)
from intake.revisions import GridRevision
from intake.source_state import load_processable_revision
from intake.store import IntakeStore


def _trace_sections(revision: GridRevision, threshold2: int) -> tuple[CellSection, ...]:
    grid = revision.grid
    rows, cols = grid.cell_shape
    sections = []
    for row in range(rows):
        for col in range(cols):
            sections.extend(classify_cell(row, col, grid.cell_corners(row, col), threshold2))
    return tuple(sections)


def assemble_evidence(revision: GridRevision, threshold2: int) -> ContourEvidence:
    rows, cols = revision.grid.cell_shape
    return ContourEvidence(
        revision.revision_id, threshold2, rows, cols, _trace_sections(revision, threshold2)
    )


def assemble_hotspot_evidence(revision: GridRevision, threshold2: int) -> HotspotEvidence:
    rows, cols = revision.grid.cell_shape
    return HotspotEvidence(
        revision_id=revision.revision_id,
        threshold2=threshold2,
        rows=rows,
        cols=cols,
        sections=_trace_sections(revision, threshold2),
        batch_id=revision.source.batch_id,
        vertices=revision.grid.vertices,
    )


def freeze_contour(
    intake: IntakeStore,
    archive: ArchiveStore,
    revision_id: str,
    threshold: object,
    *,
    fail_before_commit: bool = False,
) -> str:
    threshold2 = parse_half_threshold(threshold)
    revision = load_processable_revision(intake, revision_id)
    evidence = assemble_evidence(revision, threshold2)
    return publish_artifact(archive, evidence, fail_before_commit=fail_before_commit)


def freeze_hotspots(
    intake: IntakeStore,
    archive: ArchiveStore,
    revision_id: str,
    threshold: object,
    *,
    fail_before_commit: bool = False,
) -> str:
    threshold2 = parse_half_threshold(threshold)
    revision = load_processable_revision(intake, revision_id)
    evidence = assemble_hotspot_evidence(revision, threshold2)
    return publish_artifact(archive, evidence, fail_before_commit=fail_before_commit)
