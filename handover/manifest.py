import json
from dataclasses import dataclass

from archive.codec import canonical_json
from review.report import AuditReport, report_from_record, report_to_record


@dataclass(frozen=True)
class HandoverManifest:
    shift_id: str
    artifact_id: str
    report: AuditReport


def validate_shift(shift_id: str) -> None:
    if not isinstance(shift_id, str) or not shift_id.strip():
        raise ValueError('shift_id must be nonblank text')


def build_manifest(shift_id: str, artifact_id: str, report: AuditReport) -> HandoverManifest:
    validate_shift(shift_id)
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError('invalid declared artifact ID')
    if not isinstance(report, AuditReport) or report.artifact_id != artifact_id:
        raise ValueError('report does not identify the declared artifact')
    return HandoverManifest(shift_id, artifact_id, report)


def encode_manifest(manifest: HandoverManifest) -> bytes:
    return canonical_json({
        'shift_id': manifest.shift_id,
        'artifact_id': manifest.artifact_id,
        'report': report_to_record(manifest.report),
    })


def decode_manifest(blob: bytes) -> HandoverManifest:
    if not isinstance(blob, bytes):
        raise ValueError('manifest must be bytes')
    try:
        record = json.loads(blob)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid manifest JSON') from error
    if not isinstance(record, dict) or record.keys() != {'shift_id', 'artifact_id', 'report'}:
        raise ValueError('invalid manifest record')
    report = report_from_record(record['report'])
    return build_manifest(record['shift_id'], record['artifact_id'], report)
