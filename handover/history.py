from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from handover.manifest import validate_shift
from handover.receipt import HandoverReceipt, receipt_from_row
from handover.store import HandoverStore


def load_handover(
    store: HandoverStore, archive: ArchiveStore, receipt_id: str
) -> tuple[HandoverReceipt, bytes]:
    if not isinstance(receipt_id, str) or not receipt_id:
        raise ValueError('invalid receipt ID')
    row = store.read_by_receipt(receipt_id)
    if row is None:
        raise ValueError('unknown receipt')
    receipt = receipt_from_row(row)
    return receipt, pickup_artifact(archive, receipt.manifest.artifact_id)


def list_shift_handovers(store: HandoverStore, shift_id: str) -> tuple[HandoverReceipt, ...]:
    validate_shift(shift_id)
    return tuple(receipt_from_row(row) for row in store.list_by_shift(shift_id))
