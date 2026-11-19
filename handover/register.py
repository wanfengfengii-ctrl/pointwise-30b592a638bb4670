from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from handover.manifest import build_manifest
from handover.receipt import HandoverReceipt, issue_receipt
from handover.store import HandoverStore
from review.report import AuditReport, audit_contour


def ack_handover(
    archive: ArchiveStore,
    handovers: HandoverStore,
    shift_id: str,
    report: AuditReport,
    artifact_id: str,
) -> HandoverReceipt:
    manifest = build_manifest(shift_id, artifact_id, report)
    published_report = audit_contour(pickup_artifact(archive, artifact_id))
    if report != published_report:
        raise ValueError('report content does not match the published artifact')
    return issue_receipt(handovers, manifest)
