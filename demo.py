import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.codec import decode_artifact
from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour, freeze_hotspots
from freeze.field_view import inspect_cell
from handover.history import load_handover
from handover.register import ack_handover
from handover.store import HandoverStore
from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.report import audit_contour, compare_hotspots


def open_stores(connection):
    stores = IntakeStore(connection), ArchiveStore(connection), HandoverStore(connection)
    for store in stores:
        store.initialize()
    return stores


def line_summary(report):
    return [
        {'sections': [list(ref.sides) for ref in component.sections],
         'outer_points': [[str(x), str(y)] for x, y in (port.point for port in component.boundary)]}
        for component in report.components
    ]


def emit(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError(f'{case_id}: {actual!r}, downstream {downstream_actual!r}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def main():
    sample_path = Path(__file__).resolve().parent / 'samples' / 'grids.json'
    samples = json.loads(sample_path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='kiln-handover-') as temporary:
        database = Path(temporary) / 'handover.sqlite3'
        with closing(sqlite3.connect(database)) as connection:
            intake, archive, _ = open_stores(connection)
            revisions, artifacts, carriers, field = {}, {}, {}, {}
            for name in ('asymmetric', 'four_arm', 'peak'):
                sample = samples[name]
                revision = ingest_grid(intake, name, sample['vertices'])
                artifact = freeze_contour(intake, archive, revision, sample['threshold'])
                revisions[name] = revision
                artifacts[name] = artifact
                carriers[name] = pickup_artifact(archive, artifact)
                field[name] = inspect_cell(archive, artifact, (0, 0))
            disable_source(intake, revisions['four_arm'])

        asymmetric = audit_contour(carriers['asymmetric'])
        four_arm = audit_contour(carriers['four_arm'])
        peak = audit_contour(carriers['peak'])
        emit(
            'v2.asymmetric', samples['asymmetric'], [['N', 'W'], ['E', 'S']],
            [list(section.sides) for section in field['asymmetric']],
            [{'sections': [['N', 'W']], 'outer_points': [['17/22', '0'], ['0', '17/22']]},
             {'sections': [['E', 'S']], 'outer_points': [['1', '5/6'], ['5/6', '1']]}],
            line_summary(asymmetric),
            ['freeze/cell_topology.py', 'freeze/field_view.py', 'review/report.py'],
            '双线性面的鞍点温度为 33/14。5/2 在其上方，两个高角分离。沿四边手算线性插值。',
        )
        emit(
            'v3.four_arm', samples['four_arm'], [['N', 'E', 'S', 'W']],
            [list(section.sides) for section in field['four_arm']],
            [{'sections': [['N', 'E', 'S', 'W']],
              'outer_points': [['1/2', '0'], ['1', '1/2'], ['1/2', '1'], ['0', '1/2']]}],
            line_summary(four_arm),
            ['freeze/assemble.py', 'archive/pickup.py', 'review/ports.py', 'review/stitch.py'],
            '减去阈值后的温度面是 2(x−1/2)(y−1/2)，两条中线在中心相交。',
        )

        with closing(sqlite3.connect(database)) as connection:
            intake, archive, handovers = open_stores(connection)
            receipt = ack_handover(archive, handovers, 'night-1', peak, artifacts['peak'])
            rescan = samples['rescan']
            new_revision = ingest_grid(intake, 'peak', rescan['vertices'], revisions['peak'])
            disable_source(intake, revisions['peak'])
            new_artifact = freeze_contour(intake, archive, new_revision, rescan['threshold'])

        with closing(sqlite3.connect(database)) as connection:
            _, archive, handovers = open_stores(connection)
            historical, historical_carrier = load_handover(handovers, archive, receipt.receipt_id)
            new_carrier = pickup_artifact(archive, new_artifact)
        emit(
            'v4.reopen_history', {'first': samples['peak'], 'second': samples['rescan']},
            {'old_source_kept': True, 'same_carrier': True, 'same_report': True},
            {'old_source_kept': historical.manifest.artifact_id == artifacts['peak'],
             'same_carrier': historical_carrier == carriers['peak'],
             'same_report': historical.manifest.report == peak},
            {'old': [{'sections': [['E', 'S'], ['S', 'W'], ['N', 'E'], ['N', 'W']],
                      'outer_points': []}], 'new': []},
            {'old': line_summary(audit_contour(historical_carrier)),
             'new': line_summary(audit_contour(new_carrier))},
            ['intake/source_state.py', 'handover/history.py', 'review/components.py'],
            '旧图四个单元围绕唯一高点连成闭环。新图所有顶点均低于阈值。',
        )

        scan = samples['hotspot_scan']
        rescan_hot = samples['hotspot_rescan']
        with closing(sqlite3.connect(database)) as connection:
            intake, archive, _ = open_stores(connection)
            scan_revision = ingest_grid(intake, 'kiln-9', scan['vertices'])
            scan_artifact = freeze_hotspots(intake, archive, scan_revision, scan['threshold'])
            rescan_revision = ingest_grid(
                intake, 'kiln-9', rescan_hot['vertices'], predecessor=scan_revision
            )
            disable_source(intake, scan_revision)
            rescan_artifact = freeze_hotspots(
                intake, archive, rescan_revision, rescan_hot['threshold']
            )

        with closing(sqlite3.connect(database)) as connection:
            intake, archive, _ = open_stores(connection)
            try:
                freeze_hotspots(intake, archive, scan_revision, scan['threshold'])
            except ValueError:
                source_stopped = True
            else:
                source_stopped = False
            scan_carrier = pickup_artifact(archive, scan_artifact)
            rescan_carrier = pickup_artifact(archive, rescan_artifact)

        comparison = compare_hotspots(scan_carrier, rescan_carrier)
        reclaimed = (
            decode_artifact(scan_carrier).artifact_id == scan_artifact
            and decode_artifact(rescan_carrier).artifact_id == rescan_artifact
        )
        emit(
            'v5.hotspot_compare',
            {'batch': 'kiln-9', 'old': scan, 'new': rescan_hot},
            {'source_stopped': True, 'reclaimed_by_original_id': True},
            {'source_stopped': source_stopped, 'reclaimed_by_original_id': reclaimed},
            {
                'old_regions': [[[0, 0], [0, 1], [0, 2]]],
                'new_regions': [[[0, 0]], [[0, 2]]],
                'old_port_regions': [[0, 0], [0, 0]],
                'new_port_regions': [[0, 0], [1, 1]],
                'matches': [[0, 0], [0, 1]],
                'splits': [0], 'merges': [], 'disappeared': [], 'born': [],
            },
            {
                'old_regions': comparison['old']['regions'],
                'new_regions': comparison['new']['regions'],
                'old_port_regions': comparison['old']['port_regions'],
                'new_port_regions': comparison['new']['port_regions'],
                'matches': comparison['matches'],
                'splits': comparison['splits'],
                'merges': comparison['merges'],
                'disappeared': comparison['disappeared'],
                'born': comparison['born'],
            },
            ['freeze/assemble.py', 'archive/codec.py', 'review/hotspots.py', 'review/report.py'],
            '旧图三个热顶点连成一区；复扫中点变冷后断为两区。停源重开按原号领取，关库后仅凭两份字节对照。',
        )


if __name__ == '__main__':
    main()
