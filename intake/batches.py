from dataclasses import dataclass

from intake.store import IntakeStore


@dataclass(frozen=True)
class BatchSource:
    batch_id: str
    predecessor: str | None


def resolve_batch_predecessor(
    store: IntakeStore, batch_id: str, predecessor: str | None
) -> BatchSource:
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('batch_id must be nonblank text')
    if predecessor is not None and (
        not isinstance(predecessor, str) or not predecessor.strip()
    ):
        raise ValueError('predecessor must be a revision ID')

    current = store.read_batch_head(batch_id)
    if predecessor is not None and predecessor != current:
        raise ValueError('predecessor must be the current revision of this batch')
    return BatchSource(batch_id, current)
