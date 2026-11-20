"""核验入口：全部原回归 + 新版热点封存到断库对照的业务链。

依次运行 unittest 全部回归与新版业务链检查；任一失败以非零退出码结束。
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent

from archive.catalog import list_artifacts
from archive.codec import canonical_json
from archive.pickup import pickup_artifact
from archive.publish import PublishAborted
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour, freeze_hotspots
from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.report import compare_hotspots


def run_regressions() -> bool:
    completed = subprocess.run(
        [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests'],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode == 0


def forge_north_quarter(carrier: bytes) -> bytes:
    """把四臂证据的北边比例从 1/2 改为 1/4 并重算摘要。"""
    body = json.loads(carrier)['body']
    for section in body['sections']:
        for port in section['ports']:
            if port[0] == 'N':
                port[1][1] = [1, 4]
                digest = hashlib.sha256(canonical_json(body)).hexdigest()
                return canonical_json({'body': body, 'sha256': digest})
    raise AssertionError('expected a north port in the fixture')


def check_hotspot_chain() -> bool:
    failures = []

    def expect(name, condition):
        print(f'CHAIN {"PASS" if condition else "FAIL"} {name}')
        if not condition:
            failures.append(name)

    with TemporaryDirectory(prefix='kiln-verify-') as temporary:
        database = Path(temporary) / 'verify.sqlite3'
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
            try:
                freeze_hotspots(intake, archive, old_revision, '1/2')
            except ValueError:
                stopped = True
            else:
                stopped = False
            try:
                freeze_hotspots(intake, archive, new_revision, '1/2', fail_before_commit=True)
            except PublishAborted as aborted:
                candidate = aborted.artifact_id
            else:
                candidate = None
            catalog = tuple(item.artifact_id for item in list_artifacts(archive))

        with closing(sqlite3.connect(database)) as connection:
            archive = ArchiveStore(connection)
            archive.initialize()
            old_carrier = pickup_artifact(archive, old_artifact)
            new_carrier = pickup_artifact(archive, new_artifact)
            try:
                if candidate is not None:
                    pickup_artifact(archive, candidate)
            except ValueError:
                candidate_blocked = True
            else:
                candidate_blocked = candidate is None

        comparison = compare_hotspots(old_carrier, new_carrier)

    expect('停源后旧修订不可再封存', stopped)
    expect(
        '中断候选号不留成果且原成果可复领',
        candidate is not None and candidate_blocked and catalog == (old_artifact, new_artifact),
    )
    expected = {
        'batch_id': 'kiln-9',
        'threshold2': 1,
        'cell_shape': [1, 2],
        'old_regions': [[[0, 0], [0, 1], [0, 2]]],
        'new_regions': [[[0, 0]], [[0, 2]]],
        'old_port_regions': [[0, 0], [0, 0]],
        'new_port_regions': [[0, 0], [1, 1]],
        'matches': [[0, 0], [0, 1]],
        'splits': [0],
        'merges': [],
        'disappeared': [],
        'born': [],
    }
    actual = {
        'batch_id': comparison['batch_id'],
        'threshold2': comparison['threshold2'],
        'cell_shape': comparison['cell_shape'],
        'old_regions': comparison['old']['regions'],
        'new_regions': comparison['new']['regions'],
        'old_port_regions': comparison['old']['port_regions'],
        'new_port_regions': comparison['new']['port_regions'],
        'matches': comparison['matches'],
        'splits': comparison['splits'],
        'merges': comparison['merges'],
        'disappeared': comparison['disappeared'],
        'born': comparison['born'],
    }
    expect('断库对照结果与手算一致', actual == expected)
    if actual != expected:
        print('CHAIN expected ' + json.dumps(expected, sort_keys=True))
        print('CHAIN actual   ' + json.dumps(actual, sort_keys=True))

    connection = sqlite3.connect(':memory:')
    with closing(connection):
        intake, archive = IntakeStore(connection), ArchiveStore(connection)
        intake.initialize()
        archive.initialize()
        four_arm_old = ingest_grid(intake, 'kiln-8', [[1, 0], [0, 1]])
        four_arm_new = ingest_grid(intake, 'kiln-8', [[0, 1], [1, 0]], predecessor=four_arm_old)
        v2_old = pickup_artifact(archive, freeze_hotspots(intake, archive, four_arm_old, '1/2'))
        v2_new = pickup_artifact(archive, freeze_hotspots(intake, archive, four_arm_new, '1/2'))
        v1_old = pickup_artifact(archive, freeze_contour(intake, archive, four_arm_old, '1/2'))

    for name, first, second in (
        ('旧版载荷被拒收', v1_old, v2_new),
        ('重算摘要的矛盾四臂证据被拒收', forge_north_quarter(v2_old), v2_new),
    ):
        try:
            compare_hotspots(first, second)
        except ValueError:
            rejected = True
        else:
            rejected = False
        expect(name, rejected)
    return not failures


def main() -> int:
    regressions_ok = run_regressions()
    chain_ok = check_hotspot_chain()
    print('VERIFY regressions:', 'PASS' if regressions_ok else 'FAIL')
    print('VERIFY hotspot chain:', 'PASS' if chain_ok else 'FAIL')
    return 0 if regressions_ok and chain_ok else 1


if __name__ == '__main__':
    sys.exit(main())
