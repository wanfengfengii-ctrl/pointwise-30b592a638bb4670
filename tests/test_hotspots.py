import hashlib
import json
import sqlite3
import unittest
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.catalog import list_artifacts
from archive.codec import canonical_json
from archive.pickup import pickup_artifact
from archive.publish import PublishAborted
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour, freeze_hotspots
from freeze.field_view import inspect_cell
from handover.history import load_handover
from handover.register import ack_handover
from handover.store import HandoverStore
from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.hotspots import compare_hotspots
from review.report import audit_contour
from review.report import compare_hotspots as report_compare


def freeze_carriers(grids, threshold='1/2', batch='kiln-7'):
    """同批依次登记并封存各修订；连接关闭后只返回编号与离线字节。"""
    connection = sqlite3.connect(':memory:')
    intake, archive = IntakeStore(connection), ArchiveStore(connection)
    intake.initialize()
    archive.initialize()
    frozen = []
    for grid in grids:
        revision = ingest_grid(intake, batch, grid)
        artifact = freeze_hotspots(intake, archive, revision, threshold)
        frozen.append((revision, artifact, pickup_artifact(archive, artifact)))
    connection.close()
    return frozen


def contour_carrier(grid, threshold='1/2', batch='kiln-7'):
    connection = sqlite3.connect(':memory:')
    intake, archive = IntakeStore(connection), ArchiveStore(connection)
    intake.initialize()
    archive.initialize()
    revision = ingest_grid(intake, batch, grid)
    artifact = freeze_contour(intake, archive, revision, threshold)
    carrier = pickup_artifact(archive, artifact)
    connection.close()
    return carrier


def reseal(body):
    """按篡改后的正文重算摘要，得到摘要正确但内容矛盾的载荷。"""
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    return canonical_json({'body': body, 'sha256': digest})


class HotspotFreezeTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.intake = IntakeStore(self.connection)
        self.archive = ArchiveStore(self.connection)
        self.intake.initialize()
        self.archive.initialize()

    def test_payload_format_and_shared_catalog(self):
        revision = ingest_grid(self.intake, 'batch-9', [[11, 0], [0, 3]])
        artifact = freeze_hotspots(self.intake, self.archive, revision, Fraction(5, 2))
        carrier = pickup_artifact(self.archive, artifact)
        body = json.loads(carrier)['body']
        self.assertEqual(body['version'], 2)
        self.assertEqual(body['artifact_id'], artifact)
        self.assertEqual(body['revision_id'], revision)
        self.assertEqual(body['batch_id'], 'batch-9')
        self.assertEqual(body['threshold2'], 5)
        self.assertEqual((body['rows'], body['cols']), (1, 1))
        self.assertEqual(body['vertices'], [[11, 0], [0, 3]])

        v1_artifact = freeze_contour(self.intake, self.archive, revision, '5/2')
        v1_body = json.loads(pickup_artifact(self.archive, v1_artifact))['body']
        self.assertEqual(v1_body['version'], 1)
        self.assertEqual(body['sections'], v1_body['sections'])
        self.assertEqual(
            [item.artifact_id for item in list_artifacts(self.archive)],
            [artifact, v1_artifact],
        )

        sections = inspect_cell(self.archive, artifact, (0, 0))
        self.assertEqual(tuple(section.sides for section in sections), (('N', 'W'), ('E', 'S')))
        report = audit_contour(carrier)
        self.assertEqual(
            (report.artifact_id, report.revision_id, report.threshold2), (artifact, revision, 5)
        )
        self.assertEqual(len(report.components), 2)

    def test_unknown_or_disabled_revision_rejected(self):
        with self.assertRaises(ValueError):
            freeze_hotspots(self.intake, self.archive, 'unknown', '1/2')
        revision = ingest_grid(self.intake, 'batch-9', [[1, 0], [0, 1]])
        disable_source(self.intake, revision)
        with self.assertRaises(ValueError):
            freeze_hotspots(self.intake, self.archive, revision, '1/2')
        self.assertEqual(list_artifacts(self.archive), ())

    def test_invalid_threshold_leaves_no_artifact(self):
        revision = ingest_grid(self.intake, 'batch-9', [[1, 0], [0, 1]])
        for invalid in (1, Fraction(1), '1', '1/3', '1/0', 0.5, True, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                freeze_hotspots(self.intake, self.archive, revision, invalid)
        self.assertEqual(list_artifacts(self.archive), ())

    def test_abort_leaves_no_artifact(self):
        revision = ingest_grid(self.intake, 'batch-9', [[1, 0], [0, 1]])
        artifact = freeze_hotspots(self.intake, self.archive, revision, '1/2')
        carrier = pickup_artifact(self.archive, artifact)
        with self.assertRaises(PublishAborted) as failed:
            freeze_hotspots(self.intake, self.archive, revision, '1/2', fail_before_commit=True)
        candidate = failed.exception.artifact_id
        self.assertEqual([item.artifact_id for item in list_artifacts(self.archive)], [artifact])
        with self.assertRaises(ValueError):
            pickup_artifact(self.archive, candidate)
        self.assertEqual(pickup_artifact(self.archive, artifact), carrier)


class CompareCaseTests(unittest.TestCase):
    def compare(self, old_grid, new_grid, threshold='1/2'):
        (old_ids, new_ids) = freeze_carriers([old_grid, new_grid], threshold)[:2]
        result = compare_hotspots(old_ids[2], new_ids[2])
        json.dumps(result)
        return result, old_ids, new_ids

    def test_entrypoint_is_reexported(self):
        self.assertIs(report_compare, compare_hotspots)

    def test_opposite(self):
        result, (old_revision, old_artifact, _), (new_revision, new_artifact, _) = self.compare(
            [[1, 0], [0, 1]], [[0, 1], [1, 0]]
        )
        self.assertEqual(result['batch_id'], 'kiln-7')
        self.assertEqual(result['threshold2'], 1)
        self.assertEqual(result['cell_shape'], [1, 1])
        self.assertEqual(result['old'], {
            'artifact_id': old_artifact,
            'revision_id': old_revision,
            'regions': [[[0, 0]], [[1, 1]]],
            'port_regions': [[0, 1, 1, 0]],
        })
        self.assertEqual(result['new'], {
            'artifact_id': new_artifact,
            'revision_id': new_revision,
            'regions': [[[0, 1]], [[1, 0]]],
            'port_regions': [[0, 0, 1, 1]],
        })
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['splits'], [])
        self.assertEqual(result['merges'], [])
        self.assertEqual(result['disappeared'], [0, 1])
        self.assertEqual(result['born'], [0, 1])

    def test_split(self):
        result, _, _ = self.compare([[1, 1, 1], [0, 0, 0]], [[1, 0, 1], [0, 0, 0]])
        self.assertEqual(result['old']['regions'], [[[0, 0], [0, 1], [0, 2]]])
        self.assertEqual(result['new']['regions'], [[[0, 0]], [[0, 2]]])
        self.assertEqual(result['old']['port_regions'], [[0, 0], [0, 0]])
        self.assertEqual(result['new']['port_regions'], [[0, 0], [1, 1]])
        self.assertEqual(result['matches'], [[0, 0], [0, 1]])
        self.assertEqual(result['splits'], [0])
        self.assertEqual(result['merges'], [])
        self.assertEqual(result['disappeared'], [])
        self.assertEqual(result['born'], [])

    def test_split_reversed_is_merge(self):
        (old_ids, new_ids) = freeze_carriers([[[1, 1, 1], [0, 0, 0]], [[1, 0, 1], [0, 0, 0]]])
        result = compare_hotspots(new_ids[2], old_ids[2])
        self.assertEqual(result['matches'], [[0, 0], [1, 0]])
        self.assertEqual(result['splits'], [])
        self.assertEqual(result['merges'], [0])
        self.assertEqual(result['disappeared'], [])
        self.assertEqual(result['born'], [])

    def test_cross(self):
        result, _, _ = self.compare(
            [[1, 1, 1], [0, 0, 0], [1, 1, 1]], [[1, 0, 1]] * 3
        )
        self.assertEqual(
            result['old']['regions'], [[[0, 0], [0, 1], [0, 2]], [[2, 0], [2, 1], [2, 2]]]
        )
        self.assertEqual(
            result['new']['regions'], [[[0, 0], [1, 0], [2, 0]], [[0, 2], [1, 2], [2, 2]]]
        )
        self.assertEqual(result['old']['port_regions'], [[0, 0], [0, 0], [1, 1], [1, 1]])
        self.assertEqual(result['new']['port_regions'], [[0, 0], [1, 1], [0, 0], [1, 1]])
        self.assertEqual(result['matches'], [[0, 0], [0, 1], [1, 0], [1, 1]])
        self.assertEqual(result['splits'], [0, 1])
        self.assertEqual(result['merges'], [0, 1])
        self.assertEqual(result['disappeared'], [])
        self.assertEqual(result['born'], [])

    def test_uniform(self):
        result, _, _ = self.compare([[1, 1], [1, 1]], [[0, 0], [0, 0]])
        self.assertEqual(result['old']['regions'], [[[0, 0], [0, 1], [1, 0], [1, 1]]])
        self.assertEqual(result['old']['port_regions'], [])
        self.assertEqual(result['new']['regions'], [])
        self.assertEqual(result['new']['port_regions'], [])
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['disappeared'], [0])
        self.assertEqual(result['born'], [])

    def test_saddle(self):
        result, _, _ = self.compare([[2, 0], [0, 2]], [[1, -1], [-1, 1]])
        self.assertEqual(result['old']['regions'], [[[0, 0], [1, 1]]])
        self.assertEqual(result['old']['port_regions'], [[0, 0], [0, 0]])
        self.assertEqual(result['new']['regions'], [[[0, 0]], [[1, 1]]])
        self.assertEqual(result['new']['port_regions'], [[0, 0], [1, 1]])
        self.assertEqual(result['matches'], [[0, 0], [0, 1]])
        self.assertEqual(result['splits'], [0])
        self.assertEqual(result['merges'], [])
        self.assertEqual(result['disappeared'], [])
        self.assertEqual(result['born'], [])

    def test_same_cell_dual_branch_keeps_origins(self):
        result, _, _ = self.compare([[11, 0], [0, 3]], [[11, 0], [0, 3]], threshold='5/2')
        self.assertEqual(result['old']['regions'], [[[0, 0]], [[1, 1]]])
        self.assertEqual(result['old']['port_regions'], [[0, 0], [1, 1]])
        self.assertEqual(result['matches'], [[0, 0], [1, 1]])

    def test_detour_zones_share_one_region(self):
        grid = [
            [1, 1, 1, 1],
            [1, 1, -1, 1],
            [1, -1, 1, 1],
            [1, 1, 1, 1],
        ]
        result, _, _ = self.compare(grid, grid)
        expected_points = [
            [row, col]
            for row in range(4)
            for col in range(4)
            if (row, col) not in ((1, 2), (2, 1))
        ]
        self.assertEqual(result['old']['regions'], [expected_points])
        self.assertEqual(result['old']['port_regions'], [[0, 0]] * 8)
        self.assertEqual(result['matches'], [[0, 0]])
        self.assertEqual(result['splits'], [])
        self.assertEqual(result['merges'], [])

    def test_cross_generation_compare_is_legal(self):
        first, second, third = freeze_carriers(
            [[[1, 1], [1, 1]], [[0, 0], [0, 0]], [[1, 1], [1, 1]]]
        )
        result = compare_hotspots(first[2], third[2])
        self.assertEqual(result['matches'], [[0, 0]])
        vanished = compare_hotspots(first[2], second[2])
        self.assertEqual(vanished['disappeared'], [0])
        self.assertEqual(vanished['born'], [])


class CompareRejectionTests(unittest.TestCase):
    def setUp(self):
        frozen = freeze_carriers([[[1, 0], [0, 1]], [[0, 1], [1, 0]]])
        self.old_revision, self.old_artifact, self.old_carrier = frozen[0]
        self.new_revision, self.new_artifact, self.new_carrier = frozen[1]

    def test_version_one_carrier_rejected(self):
        v1 = contour_carrier([[1, 0], [0, 1]])
        for first, second in ((v1, self.new_carrier), (self.old_carrier, v1), (v1, v1)):
            with self.subTest(first=first is v1, second=second is v1):
                with self.assertRaises(ValueError):
                    compare_hotspots(first, second)

    def test_same_revision_rejected(self):
        with self.assertRaises(ValueError):
            compare_hotspots(self.old_carrier, self.old_carrier)

    def test_mismatched_batch_rejected(self):
        other = freeze_carriers([[[1, 0], [0, 1]]], batch='kiln-8')[0]
        with self.assertRaises(ValueError):
            compare_hotspots(self.old_carrier, other[2])

    def test_mismatched_shape_rejected(self):
        other = freeze_carriers([[[1, 0, 0], [0, 1, 0]]])[0]
        with self.assertRaises(ValueError):
            compare_hotspots(self.old_carrier, other[2])

    def test_mismatched_threshold_rejected(self):
        other = freeze_carriers([[[2, 0], [0, 2]]], threshold='3/2')[0]
        with self.assertRaises(ValueError):
            compare_hotspots(self.old_carrier, other[2])

    def test_garbage_rejected(self):
        for bad in (b'', b'not json', b'{}', 'text', None, 42):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    compare_hotspots(bad, self.new_carrier)
                with self.assertRaises(ValueError):
                    compare_hotspots(self.old_carrier, bad)

    def test_checksum_damage_rejected(self):
        envelope = json.loads(self.old_carrier)
        envelope['body']['threshold2'] = 3
        forged = json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('ascii')
        with self.assertRaises(ValueError):
            compare_hotspots(forged, self.new_carrier)

    def test_noncanonical_carrier_rejected(self):
        pretty = json.dumps(json.loads(self.old_carrier), indent=1).encode('utf-8')
        with self.assertRaises(ValueError):
            compare_hotspots(pretty, self.new_carrier)

    def test_contradictory_crossing_rejected_with_valid_checksum(self):
        body = json.loads(self.old_carrier)['body']
        (section,) = body['sections']
        north = section['ports'][0]
        self.assertEqual(north[0], 'N')
        self.assertEqual(north[1][1], [1, 2])
        # 四臂证据原四边比例均为 1/2；只把北边比例改为 1/4 并重算摘要。
        north[1][1] = [1, 4]
        forged = reseal(body)
        with self.assertRaises(ValueError):
            compare_hotspots(forged, self.new_carrier)
        with self.assertRaises(ValueError):
            audit_contour(forged)

    def test_contradictory_vertices_rejected_with_valid_checksum(self):
        body = json.loads(self.old_carrier)['body']
        body['vertices'][0][0] = 3
        with self.assertRaises(ValueError):
            compare_hotspots(reseal(body), self.new_carrier)

    def test_contradictory_branch_partition_rejected(self):
        frozen = freeze_carriers([[[2, 0], [0, 2]], [[1, -1], [-1, 1]]])
        body = json.loads(frozen[0][2])['body']
        first, second = body['sections']
        self.assertEqual([port[0] for port in first['ports']], ['N', 'E'])
        self.assertEqual([port[0] for port in second['ports']], ['S', 'W'])
        # 同格双支换成另一组配对并重算摘要，与原段接法矛盾。
        body['sections'] = [
            {'cell': [0, 0], 'ports': [first['ports'][0], second['ports'][1]]},
            {'cell': [0, 0], 'ports': [first['ports'][1], second['ports'][0]]},
        ]
        with self.assertRaises(ValueError):
            compare_hotspots(reseal(body), frozen[1][2])


class HotspotReopenTests(unittest.TestCase):
    def test_reopen_pickup_and_offline_compare(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / 'hotspots.sqlite3'
            with closing(sqlite3.connect(database)) as connection:
                intake, archive = IntakeStore(connection), ArchiveStore(connection)
                intake.initialize()
                archive.initialize()
                old_revision = ingest_grid(intake, 'kiln-9', [[1, 1, 1], [0, 0, 0]])
                old_artifact = freeze_hotspots(intake, archive, old_revision, '1/2')
                new_revision = ingest_grid(
                    intake, 'kiln-9', [[1, 0, 1], [0, 0, 0]], predecessor=old_revision
                )
                disable_source(intake, old_revision)
                new_artifact = freeze_hotspots(intake, archive, new_revision, '1/2')
            with closing(sqlite3.connect(database)) as connection:
                archive = ArchiveStore(connection)
                archive.initialize()
                old_carrier = pickup_artifact(archive, old_artifact)
                new_carrier = pickup_artifact(archive, new_artifact)
                with self.assertRaises(ValueError):
                    freeze_hotspots(IntakeStore(connection), archive, old_revision, '1/2')
            comparison = compare_hotspots(old_carrier, new_carrier)
        self.assertEqual(comparison['batch_id'], 'kiln-9')
        self.assertEqual(comparison['old']['revision_id'], old_revision)
        self.assertEqual(comparison['new']['revision_id'], new_revision)
        self.assertEqual(comparison['matches'], [[0, 0], [0, 1]])
        self.assertEqual(comparison['splits'], [0])

    def test_handover_and_history_with_hotspot_artifact(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / 'handover.sqlite3'
            with closing(sqlite3.connect(database)) as connection:
                intake = IntakeStore(connection)
                archive = ArchiveStore(connection)
                handovers = HandoverStore(connection)
                for store in (intake, archive, handovers):
                    store.initialize()
                revision = ingest_grid(intake, 'kiln-9', [[1, 0], [0, 1]])
                artifact = freeze_hotspots(intake, archive, revision, '1/2')
                carrier = pickup_artifact(archive, artifact)
                report = audit_contour(carrier)
                receipt = ack_handover(archive, handovers, 'night', report, artifact)
                disable_source(intake, revision)
            with closing(sqlite3.connect(database)) as connection:
                archive = ArchiveStore(connection)
                handovers = HandoverStore(connection)
                archive.initialize()
                handovers.initialize()
                recovered, recovered_carrier = load_handover(
                    handovers, archive, receipt.receipt_id
                )
        self.assertEqual(recovered, receipt)
        self.assertEqual(recovered_carrier, carrier)
        self.assertEqual(recovered.manifest.report, report)


if __name__ == '__main__':
    unittest.main()
