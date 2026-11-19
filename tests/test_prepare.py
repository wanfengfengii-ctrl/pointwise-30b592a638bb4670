import sqlite3
import unittest
from fractions import Fraction

from archive.catalog import list_artifacts
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour
from freeze.field_view import inspect_cell
from intake.revisions import ingest_grid, load_revision
from intake.store import IntakeStore


class PrepareTests(unittest.TestCase):
    def setUp(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        self.intake = IntakeStore(connection)
        self.archive = ArchiveStore(connection)
        self.intake.initialize()
        self.archive.initialize()

    def freeze(self, grid, threshold='1/2'):
        revision = ingest_grid(self.intake, 'kiln-7', grid)
        return freeze_contour(self.intake, self.archive, revision, threshold)

    def test_normal_cell(self):
        artifact = self.freeze([[1, 0], [1, 0]])
        (section,) = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(section.sides, ('N', 'S'))
        self.assertEqual([crossing.point for _, crossing in section.ports], [
            (Fraction(1, 2), 0), (Fraction(1, 2), 1),
        ])

    def test_exact_crossing(self):
        artifact = self.freeze([[3, 0], [3, 0]])
        (section,) = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(section.sides, ('N', 'S'))
        self.assertEqual([crossing.point for _, crossing in section.ports], [
            (Fraction(5, 6), 0), (Fraction(5, 6), 1),
        ])

    def test_cell_lookup(self):
        artifact = self.freeze([[0, 0], [0, 0]])
        self.assertEqual(inspect_cell(self.archive, artifact, (0, 0)), ())
        with self.assertRaises(ValueError):
            inspect_cell(self.archive, 'unknown', (0, 0))
        for cell in ((1, 0), (0, 1), (-1, 0), (False, 0), (0,)):
            with self.subTest(cell=cell), self.assertRaises(ValueError):
                inspect_cell(self.archive, artifact, cell)

    def test_asymmetric_pairing(self):
        artifact = self.freeze([[11, 0], [0, 3]], Fraction(5, 2))
        first, second = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual((first.sides, second.sides), (('N', 'W'), ('E', 'S')))
        self.assertEqual([crossing.offset for _, crossing in first.ports], [Fraction(17, 22)] * 2)
        self.assertEqual([crossing.offset for _, crossing in second.ports], [Fraction(5, 6)] * 2)

    def test_critical_four_arm_cell(self):
        artifact = self.freeze([[1, 0], [0, 1]])
        (section,) = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(section.sides, ('N', 'E', 'S', 'W'))
        self.assertEqual([crossing.offset for _, crossing in section.ports], [Fraction(1, 2)] * 4)

    def test_opposite_pairing(self):
        artifact = self.freeze([[3, 0], [0, 3]])
        sections = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(tuple(section.sides for section in sections), (('N', 'E'), ('S', 'W')))

    def test_reversed_alternating_diagonal(self):
        artifact = self.freeze([[0, 3], [3, 0]])
        sections = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(tuple(section.sides for section in sections), (('N', 'W'), ('E', 'S')))

    def test_bad_grid_leaves_no_revision(self):
        with self.assertRaises(ValueError):
            ingest_grid(self.intake, 'ragged', [[1, 0], [0, 0, 0]])
        with self.assertRaises(ValueError):
            ingest_grid(self.intake, 'thin', [[1, 0]])
        self.assertEqual(self.intake.list_revision_ids(), ())
        self.assertIsNone(self.intake.read_batch_head('ragged'))

    def test_bad_temperature_leaves_no_revision(self):
        for invalid in (None, True, 2.0, '2'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ingest_grid(self.intake, 'kiln-7', [[invalid, 0], [0, 1]])
        self.assertEqual(self.intake.list_revision_ids(), ())

    def test_predecessor_must_match_this_batch_head(self):
        grid = [[1, 0], [0, 1]]
        first = ingest_grid(self.intake, 'batch-a', grid)
        foreign = ingest_grid(self.intake, 'batch-b', grid)
        second = ingest_grid(self.intake, 'batch-a', grid, predecessor=first)
        for wrong in (foreign, first):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                ingest_grid(self.intake, 'batch-a', grid, predecessor=wrong)
        self.assertEqual(self.intake.read_batch_head('batch-a'), second)
        self.assertEqual(self.intake.list_revision_ids('batch-a'), (first, second))
        self.assertEqual(self.intake.list_revision_ids('batch-b'), (foreign,))
        third = ingest_grid(self.intake, 'batch-a', grid)
        self.assertEqual(load_revision(self.intake, third).source.predecessor, second)

    def test_integer_threshold_leaves_no_artifact(self):
        revision = ingest_grid(self.intake, 'kiln-7', [[0, 0], [0, 0]])
        for invalid in (1, Fraction(1), '1', '1/3', '1/0', 0.5, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                freeze_contour(self.intake, self.archive, revision, invalid)
        self.assertEqual(list_artifacts(self.archive), ())
        self.assertEqual(inspect_cell(self.archive, self.freeze([[0, 0], [0, 0]]), (0, 0)), ())

    def test_exact_negative_and_large_half_thresholds(self):
        large = 9007199254740992
        cases = (
            ([[-1, 0], [-1, 0]], '-1/2'),
            ([[large, large + 1], [large, large + 1]], Fraction(2 * large + 1, 2)),
        )
        for grid, threshold in cases:
            with self.subTest(threshold=threshold):
                artifact = self.freeze(grid, threshold)
                (section,) = inspect_cell(self.archive, artifact, (0, 0))
                self.assertEqual(section.sides, ('N', 'S'))
                self.assertEqual(tuple(crossing.offset for _, crossing in section.ports), (Fraction(1, 2),) * 2)
