from dataclasses import dataclass
from uuid import uuid4

from handover.manifest import HandoverManifest, decode_manifest, encode_manifest
from handover.store import HandoverStore


@dataclass(frozen=True)
class HandoverReceipt:
    receipt_id: str
    manifest: HandoverManifest


def receipt_from_row(row) -> HandoverReceipt:
    receipt_id, shift_id, artifact_id, blob = row
    manifest = decode_manifest(blob)
    if (manifest.shift_id, manifest.artifact_id) != (shift_id, artifact_id):
        raise ValueError('manifest does not match the receipt binding')
    return HandoverReceipt(receipt_id, manifest)


def find_confirmation(
    store: HandoverStore, shift_id: str, artifact_id: str
) -> HandoverReceipt | None:
    row = store.read_confirmation(shift_id, artifact_id)
    return None if row is None else receipt_from_row(row)


def issue_receipt(store: HandoverStore, manifest: HandoverManifest) -> HandoverReceipt:
    with store.write_transaction():
        existing = find_confirmation(store, manifest.shift_id, manifest.artifact_id)
        if existing is not None:
            return existing
        receipt = HandoverReceipt('h-' + uuid4().hex, manifest)
        store.insert_confirmation(
            receipt.receipt_id, manifest.shift_id, manifest.artifact_id, encode_manifest(manifest)
        )
    return receipt
