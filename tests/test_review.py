import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.catalog import list_artifacts
from archive.pickup import pickup_artifact
from archive.publish import publish_artifact
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour
from freeze.edge_crossings import Crossing, EdgeId
from freeze.evidence import CellSection, ContourEvidence
from freeze.field_view import inspect_cell
from handover.history import list_shift_handovers, load_handover
from handover.register import ack_handover
from handover.store import HandoverStore
from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.report import audit_contour


PEAK = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / 'review.sqlite3'
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.intake = IntakeStore(self.connection)
        self.archive = ArchiveStore(self.connection)
        self.handovers = HandoverStore(self.connection)
        for store in (self.intake, self.archive, self.handovers):
            store.initialize()

    def freeze(self, grid, threshold='1/2'):
        revision = ingest_grid(self.intake, 'kiln-7', grid)
        artifact = freeze_contour(self.intake, self.archive, revision, threshold)
        return revision, artifact, pickup_artifact(self.archive, artifact)

    def test_closed_loop_and_idempotent_confirmation(self):
        revision, artifact, carrier = self.freeze(PEAK)
        disable_source(self.intake, revision)
        self.connection.close()
        report = audit_contour(carrier)
        self.assertEqual((report.artifact_id, report.revision_id), (artifact, revision))
        (component,) = report.components
        self.assertEqual(component.boundary, ())
        self.assertEqual([(ref.row, ref.col, ref.sides) for ref in component.sections], [
            (0, 0, ('E', 'S')), (0, 1, ('S', 'W')), (1, 0, ('N', 'E')), (1, 1, ('N', 'W')),
        ])
        with closing(sqlite3.connect(self.database)) as connection:
            archive, handovers = ArchiveStore(connection), HandoverStore(connection)
            receipt = ack_handover(archive, handovers, 'night', report, artifact)
            again = ack_handover(archive, handovers, 'night', report, artifact)
            self.assertEqual(again, receipt)
            self.assertEqual(list_shift_handovers(handovers, 'night'), (receipt,))
            self.assertEqual(load_handover(handovers, archive, receipt.receipt_id), (receipt, carrier))

    def test_four_arm_from_independent_carrier(self):
        revision = ingest_grid(self.intake, 'kiln-7', [[1, 0], [0, 1]])
        half = Fraction(1, 2)
        known_section = CellSection(0, 0, (
            ('N', Crossing(EdgeId('H', 0, 0), half)),
            ('E', Crossing(EdgeId('V', 0, 1), half)),
            ('S', Crossing(EdgeId('H', 1, 0), half)),
            ('W', Crossing(EdgeId('V', 0, 0), half)),
        ))
        artifact = publish_artifact(self.archive, ContourEvidence(revision, 1, 1, 1, (known_section,)))
        carrier = pickup_artifact(self.archive, artifact)
        disable_source(self.intake, revision)
        self.connection.close()
        report = audit_contour(carrier)
        self.assertEqual(report.artifact_id, artifact)
        (component,) = report.components
        self.assertEqual([(ref.row, ref.col, ref.sides) for ref in component.sections], [
            (0, 0, ('N', 'E', 'S', 'W')),
        ])
        self.assertEqual(tuple(port.point for port in component.boundary), (
            (half, 0), (1, half), (half, 1), (0, half),
        ))

    def test_four_arm_from_freeze(self):
        revision, artifact, carrier = self.freeze([[1, 0], [0, 1]])
        (section,) = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(section.sides, ('N', 'E', 'S', 'W'))
        disable_source(self.intake, revision)
        self.connection.close()
        (component,) = audit_contour(carrier).components
        (ref,) = component.sections
        self.assertEqual((ref.row, ref.col, ref.sides), (0, 0, ('N', 'E', 'S', 'W')))
        self.assertEqual(tuple(port.point for port in component.boundary), (
            (Fraction(1, 2), 0), (1, Fraction(1, 2)), (Fraction(1, 2), 1), (0, Fraction(1, 2)),
        ))

    def test_same_cell_branches_are_separate(self):
        _, _, carrier = self.freeze([[11, 0, 0], [0, 3, 3]], '5/2')
        first, second = audit_contour(carrier).components
        self.assertEqual([(ref.row, ref.col, ref.sides) for ref in first.sections], [(0, 0, ('N', 'W'))])
        self.assertEqual([(ref.row, ref.col, ref.sides) for ref in second.sections], [
            (0, 0, ('E', 'S')), (0, 1, ('E', 'W')),
        ])
        self.assertEqual(tuple(port.point for port in first.boundary), ((Fraction(17, 22), 0), (0, Fraction(17, 22))))
        self.assertEqual(tuple(port.point for port in second.boundary), ((Fraction(5, 6), 1), (2, Fraction(5, 6))))

    def test_parallel_tracks_use_distinct_edge_anchors(self):
        _, _, carrier = self.freeze([[1, 0, 1, 0]] * 3)
        components = audit_contour(carrier).components
        self.assertEqual(len(components), 3)
        for col, component in enumerate(components):
            with self.subTest(col=col):
                self.assertEqual([(ref.row, ref.col, ref.sides) for ref in component.sections], [
                    (0, col, ('N', 'S')), (1, col, ('N', 'S')),
                ])
                x = Fraction(2 * col + 1, 2)
                self.assertEqual(tuple(port.point for port in component.boundary), ((x, 0), (x, 2)))

    def test_corrupt_carrier_rejected_at_pickup_and_audit(self):
        _, artifact, carrier = self.freeze(PEAK)
        self.assertEqual(len(audit_contour(carrier).components), 1)
        envelope = json.loads(carrier)
        envelope['body']['threshold2'] = 3
        corrupt = json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('ascii')
        with self.connection:
            self.connection.execute('UPDATE artifacts SET payload = ? WHERE artifact_id = ?', (corrupt, artifact))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            pickup_artifact(self.archive, artifact)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            audit_contour(corrupt)

    def test_interior_ports_require_a_matching_neighbor_and_offset(self):
        revision = ingest_grid(self.intake, 'kiln-7', [[1, 0], [1, 0], [1, 0]])
        mid = Fraction(1, 2)
        section = CellSection(0, 0, (
            ('N', Crossing(EdgeId('H', 0, 0), mid)), ('S', Crossing(EdgeId('H', 1, 0), mid)),
        ))
        wrong_neighbor = CellSection(1, 0, (
            ('N', Crossing(EdgeId('H', 1, 0), Fraction(1, 3))), ('S', Crossing(EdgeId('H', 2, 0), mid)),
        ))
        for sections, message in (((section,), 'incident cells'), ((section, wrong_neighbor), 'positions')):
            with self.subTest(message=message):
                artifact = publish_artifact(self.archive, ContourEvidence(revision, 1, 2, 1, sections))
                with self.assertRaisesRegex(ValueError, message):
                    audit_contour(pickup_artifact(self.archive, artifact))

    def test_same_revision_other_artifact_cannot_confirm(self):
        revision, first, first_carrier = self.freeze(PEAK)
        second = freeze_contour(self.intake, self.archive, revision, '3/2')
        report = audit_contour(first_carrier)
        second_report = audit_contour(pickup_artifact(self.archive, second))
        self.assertEqual(second_report.components, ())
        self.assertEqual([item.revision_id for item in list_artifacts(self.archive)], [revision, revision])
        receipt = ack_handover(self.archive, self.handovers, 'night', report, first)
        with self.assertRaises(ValueError):
            ack_handover(self.archive, self.handovers, 'night', report, second)
        with self.assertRaises(ValueError):
            ack_handover(self.archive, self.handovers, 'night', replace(report, artifact_id=second), second)
        self.assertEqual(list_shift_handovers(self.handovers, 'night'), (receipt,))
        self.assertEqual(load_handover(self.handovers, self.archive, receipt.receipt_id), (receipt, first_carrier))
        second_receipt = ack_handover(self.archive, self.handovers, 'night', second_report, second)
        with self.assertRaises(ValueError):
            ack_handover(self.archive, self.handovers, 'night', report, second)
        self.assertEqual(list_shift_handovers(self.handovers, 'night'), (receipt, second_receipt))
