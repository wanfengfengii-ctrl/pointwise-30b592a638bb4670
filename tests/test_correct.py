import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.catalog import list_artifacts
from archive.pickup import pickup_artifact
from archive.publish import PublishAborted
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour
from freeze.field_view import inspect_cell
from handover.history import list_shift_handovers, load_handover
from handover.register import ack_handover
from handover.store import HandoverStore
from intake.revisions import ingest_grid, load_revision
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.report import audit_contour


PEAK = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]
CLEAR = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / 'corrections.sqlite3'
        self.open_database()

    def open_database(self):
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.intake = IntakeStore(self.connection)
        self.archive = ArchiveStore(self.connection)
        self.handovers = HandoverStore(self.connection)
        self.initialize()

    def initialize(self):
        for store in (self.intake, self.archive, self.handovers):
            store.initialize()

    def original_handover(self):
        first = ingest_grid(self.intake, 'kiln-7', PEAK)
        artifact = freeze_contour(self.intake, self.archive, first, '1/2')
        carrier = pickup_artifact(self.archive, artifact)
        report = audit_contour(carrier)
        receipt = ack_handover(self.archive, self.handovers, 'night', report, artifact)
        return first, artifact, carrier, receipt

    def test_retired_source_blocks_new_freeze_but_keeps_pickup(self):
        old, artifact, carrier, _ = self.original_handover()
        with self.assertRaises(ValueError):
            disable_source(self.intake, 'unknown')
        disable_source(self.intake, old)
        disable_source(self.intake, old)
        self.assertTrue(load_revision(self.intake, old).disabled)
        with self.assertRaises(ValueError):
            freeze_contour(self.intake, self.archive, old, '1/2')
        self.assertEqual(tuple(item.artifact_id for item in list_artifacts(self.archive)), (artifact,))
        self.assertEqual(pickup_artifact(self.archive, artifact), carrier)

    def test_reopen_history_after_correction(self):
        first, old_artifact, carrier, receipt = self.original_handover()
        old_section = inspect_cell(self.archive, old_artifact, (0, 0))
        second = ingest_grid(self.intake, 'kiln-7', CLEAR, predecessor=first)
        disable_source(self.intake, first)
        new_artifact = freeze_contour(self.intake, self.archive, second, '1/2')
        self.connection.close()
        self.open_database()

        recovered, old_carrier = load_handover(self.handovers, self.archive, receipt.receipt_id)
        self.assertEqual(recovered, receipt)
        self.assertEqual(old_carrier, carrier)
        self.assertEqual(recovered.manifest.report, audit_contour(old_carrier))
        self.assertEqual(recovered.manifest.report.revision_id, first)
        self.assertEqual(inspect_cell(self.archive, old_artifact, (0, 0)), old_section)
        (component,) = recovered.manifest.report.components
        self.assertEqual([(ref.row, ref.col, ref.sides) for ref in component.sections], [
            (0, 0, ('E', 'S')), (0, 1, ('S', 'W')), (1, 0, ('N', 'E')), (1, 1, ('N', 'W')),
        ])
        self.assertEqual(component.boundary, ())
        new_report = audit_contour(pickup_artifact(self.archive, new_artifact))
        self.assertEqual((new_report.revision_id, new_report.components), (second, ()))

    def test_repeat_init_preserves_user_records(self):
        first, old_artifact, carrier, receipt = self.original_handover()
        second = ingest_grid(self.intake, 'kiln-7', CLEAR)
        disable_source(self.intake, first)
        new_artifact = freeze_contour(self.intake, self.archive, second, '1/2')
        self.connection.close()
        self.open_database()
        self.initialize()
        self.initialize()
        self.assertEqual(self.intake.read_batch_head('kiln-7'), second)
        self.assertEqual(self.intake.list_revision_ids(), (first, second))
        old_revision = load_revision(self.intake, first)
        new_revision = load_revision(self.intake, second)
        self.assertTrue(old_revision.disabled)
        self.assertFalse(new_revision.disabled)
        self.assertEqual(old_revision.grid.vertices[1][1], 1)
        self.assertEqual(new_revision.grid.vertices[1][1], 0)
        self.assertEqual(new_revision.source.predecessor, first)
        self.assertEqual([item.artifact_id for item in list_artifacts(self.archive)], [old_artifact, new_artifact])
        self.assertEqual(list_shift_handovers(self.handovers, 'night'), (receipt,))
        self.assertEqual(load_handover(self.handovers, self.archive, receipt.receipt_id), (receipt, carrier))

    def test_rollback_visibility_after_candidate_insert(self):
        first, old_artifact, carrier, receipt = self.original_handover()
        second = ingest_grid(self.intake, 'kiln-7', CLEAR, predecessor=first)
        before = list_artifacts(self.archive)
        with self.assertRaises(PublishAborted) as failed:
            freeze_contour(self.intake, self.archive, second, '1/2', fail_before_commit=True)
        candidate_id = failed.exception.artifact_id
        self.assertEqual(list_artifacts(self.archive), before)
        self.connection.close()
        self.open_database()
        self.assertEqual(list_artifacts(self.archive), before)
        self.assertEqual(pickup_artifact(self.archive, old_artifact), carrier)
        self.assertEqual(load_handover(self.handovers, self.archive, receipt.receipt_id), (receipt, carrier))
        with self.assertRaises(ValueError):
            pickup_artifact(self.archive, candidate_id)
        with self.assertRaises(ValueError):
            ack_handover(self.archive, self.handovers, 'night', receipt.manifest.report, candidate_id)
        self.assertEqual(list_shift_handovers(self.handovers, 'night'), (receipt,))
