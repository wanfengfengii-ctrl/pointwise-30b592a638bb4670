from archive.catalog import get_published_artifact
from archive.codec import ArtifactPayload, decode_artifact
from archive.storage import ArchiveStore


def _read_pickup(store: ArchiveStore, artifact_id: str) -> tuple[ArtifactPayload, bytes]:
    record, carrier = get_published_artifact(store, artifact_id)
    payload = decode_artifact(carrier)
    if artifact_id != record.artifact_id or payload.artifact_id != record.artifact_id:
        raise ValueError('artifact identity does not match the directory')
    if payload.evidence.revision_id != record.revision_id:
        raise ValueError('artifact revision does not match the directory')
    return payload, carrier


def pickup_artifact(store: ArchiveStore, artifact_id: str) -> bytes:
    _, carrier = _read_pickup(store, artifact_id)
    return carrier


def read_artifact_payload(store: ArchiveStore, artifact_id: str) -> ArtifactPayload:
    payload, _ = _read_pickup(store, artifact_id)
    return payload
