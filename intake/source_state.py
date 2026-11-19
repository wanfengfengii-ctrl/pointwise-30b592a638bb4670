from intake.revisions import GridRevision, load_revision
from intake.store import IntakeStore


def disable_source(store: IntakeStore, revision_id: str) -> None:
    if not isinstance(revision_id, str) or not revision_id:
        raise ValueError('invalid revision ID')
    with store.write_transaction():
        if not store.set_source_disabled(revision_id):
            raise ValueError('unknown revision')


def load_processable_revision(store: IntakeStore, revision_id: str) -> GridRevision:
    revision = load_revision(store, revision_id)
    if revision.disabled:
        raise ValueError('revision source is disabled')
    return revision
