import json
from dataclasses import dataclass
from uuid import uuid4

from intake.batches import BatchSource, resolve_batch_predecessor
from intake.grid import Grid, parse_grid
from intake.store import IntakeStore


@dataclass(frozen=True)
class GridRevision:
    revision_id: str
    source: BatchSource
    grid: Grid
    disabled: bool


def ingest_grid(
    store: IntakeStore,
    batch_id: str,
    temperatures: object,
    predecessor: str | None = None,
) -> str:
    grid = parse_grid(temperatures)
    vertices = json.dumps(grid.vertices, separators=(',', ':'))
    revision_id = 'r-' + uuid4().hex
    with store.write_transaction():
        source = resolve_batch_predecessor(store, batch_id, predecessor)
        store.append_revision_row(revision_id, source.batch_id, source.predecessor, vertices)
    return revision_id


def load_revision(store: IntakeStore, revision_id: str) -> GridRevision:
    if not isinstance(revision_id, str) or not revision_id:
        raise ValueError('invalid revision ID')
    record = store.read_revision_row(revision_id)
    if record is None:
        raise ValueError('unknown revision')
    stored_id, batch_id, predecessor, vertices, disabled = record
    return GridRevision(
        stored_id, BatchSource(batch_id, predecessor), parse_grid(json.loads(vertices)), bool(disabled)
    )
