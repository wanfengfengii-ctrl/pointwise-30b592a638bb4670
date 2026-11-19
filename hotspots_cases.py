"""热图复扫样例及现有走线流程的断库检查。"""
import json
import sqlite3
from contextlib import closing

from archive.codec import decode_artifact
from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour
from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.report import audit_contour


CASES = {
    "opposite": ([[1, 0], [0, 1]], [[0, 1], [1, 0]]),
    "split": ([[1, 1, 1], [0, 0, 0]], [[1, 0, 1], [0, 0, 0]]),
    "cross": ([[1, 1, 1], [0, 0, 0], [1, 1, 1]], [[1, 0, 1]] * 3),
    "uniform": ([[1, 1], [1, 1]], [[0, 0], [0, 0]]),
    "saddle": ([[2, 0], [0, 2]], [[1, -1], [-1, 1]]),
}


def v1_carriers(case):
    with closing(sqlite3.connect(":memory:")) as connection:
        intake, archive = IntakeStore(connection), ArchiveStore(connection)
        intake.initialize()
        archive.initialize()
        old_grid, new_grid = CASES[case]
        old_id = ingest_grid(intake, case, old_grid)
        new_id = ingest_grid(intake, case, new_grid, predecessor=old_id)
        artifact_ids = [freeze_contour(intake, archive, revision, "1/2")
                        for revision in (old_id, new_id)]
        for revision in (old_id, new_id):
            disable_source(intake, revision)
        return tuple(pickup_artifact(archive, item) for item in artifact_ids)


def main():
    expected = {
        "opposite": ((('NESW',), ('NESW',)), (1, 1)),
        "uniform": (((), ()), (0, 0)),
        "saddle": ((('NE', 'SW'), ('NW', 'ES')), (2, 2)),
    }
    for case, (expected_sides, expected_counts) in expected.items():
        carriers = v1_carriers(case)
        tables = tuple(decode_artifact(carrier).evidence.sections for carrier in carriers)
        sides = tuple(tuple("".join(section.sides) for section in table) for table in tables)
        counts = tuple(len(audit_contour(carrier).components) for carrier in carriers)
        if (sides, counts) != (expected_sides, expected_counts):
            raise AssertionError(f"{case}: unexpected V1 sections or line count: {(sides, counts)}")
        same_sections = tables[0] == tables[1]
        if same_sections != (case in ("opposite", "uniform")):
            raise AssertionError(f"{case}: unexpected V1 section equality")
        print(json.dumps({"case": case, "sections": sides, "line_counts": counts,
                          "same_sections": same_sections}, sort_keys=True))


if __name__ == "__main__":
    main()
