from uuid import uuid4

from archive.codec import ArtifactPayload, decode_artifact, encode_artifact
from archive.storage import ArchiveStore
from freeze.evidence import ContourEvidence


class PublishAborted(RuntimeError):
    def __init__(self, artifact_id: str):
        super().__init__(f'publication stopped before commit for {artifact_id}')
        self.artifact_id = artifact_id


def publish_artifact(
    archive: ArchiveStore, evidence: ContourEvidence, *, fail_before_commit: bool = False
) -> str:
    artifact_id = 'a-' + uuid4().hex
    carrier = encode_artifact(ArtifactPayload(artifact_id, evidence))
    decode_artifact(carrier)
    with archive.write_transaction():
        archive.insert_artifact(artifact_id, evidence.revision_id, carrier)
        if fail_before_commit:
            raise PublishAborted(artifact_id)
    return artifact_id
