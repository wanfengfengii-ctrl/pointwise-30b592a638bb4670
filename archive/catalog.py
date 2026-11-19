from dataclasses import dataclass

from archive.storage import ArchiveStore


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    revision_id: str


def get_published_artifact(store: ArchiveStore, artifact_id: str) -> tuple[ArtifactRecord, bytes]:
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError('invalid artifact ID')
    row = store.read_artifact_row(artifact_id)
    if row is None:
        raise ValueError('unknown artifact')
    stored_id, revision_id, payload = row
    return ArtifactRecord(stored_id, revision_id), payload


def list_artifacts(store: ArchiveStore) -> tuple[ArtifactRecord, ...]:
    return tuple(ArtifactRecord(*row) for row in store.list_artifact_rows())
