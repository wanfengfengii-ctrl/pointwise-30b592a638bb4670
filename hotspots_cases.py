"""热图复扫样例及现有走线流程的断库检查。"""
import json
import sqlite3
from contextlib import closing

from archive.codec import decode_artifact
from archive.pickup import pickup_artifact
from archive.storage import ArchiveStore
from freeze.assemble import freeze_contour, freeze_hotspots
from intake.revisions import ingest_grid
from intake.source_state import disable_source
from intake.store import IntakeStore
from review.report import audit_contour, compare_hotspots


CASES = {
    "opposite": ([[1, 0], [0, 1]], [[0, 1], [1, 0]]),
    "split": ([[1, 1, 1], [0, 0, 0]], [[1, 0, 1], [0, 0, 0]]),
    "cross": ([[1, 1, 1], [0, 0, 0], [1, 1, 1]], [[1, 0, 1]] * 3),
    "uniform": ([[1, 1], [1, 1]], [[0, 0], [0, 0]]),
    "saddle": ([[2, 0], [0, 2]], [[1, -1], [-1, 1]]),
}

# HOTSPOTS.md 小样例记录的对照结果（区域、端口热区号及对应关系）。
COMPARE_EXPECTED = {
    "opposite": {
        "old": {"regions": [[[0, 0]], [[1, 1]]], "port_regions": [[0, 1, 1, 0]]},
        "new": {"regions": [[[0, 1]], [[1, 0]]], "port_regions": [[0, 0, 1, 1]]},
        "matches": [], "splits": [], "merges": [], "disappeared": [0, 1], "born": [0, 1],
    },
    "split": {
        "old": {"regions": [[[0, 0], [0, 1], [0, 2]]], "port_regions": [[0, 0], [0, 0]]},
        "new": {"regions": [[[0, 0]], [[0, 2]]], "port_regions": [[0, 0], [1, 1]]},
        "matches": [[0, 0], [0, 1]], "splits": [0], "merges": [], "disappeared": [], "born": [],
    },
    "cross": {
        "old": {"regions": [[[0, 0], [0, 1], [0, 2]], [[2, 0], [2, 1], [2, 2]]],
                "port_regions": [[0, 0], [0, 0], [1, 1], [1, 1]]},
        "new": {"regions": [[[0, 0], [1, 0], [2, 0]], [[0, 2], [1, 2], [2, 2]]],
                "port_regions": [[0, 0], [1, 1], [0, 0], [1, 1]]},
        "matches": [[0, 0], [0, 1], [1, 0], [1, 1]], "splits": [0, 1], "merges": [0, 1],
        "disappeared": [], "born": [],
    },
    "uniform": {
        "old": {"regions": [[[0, 0], [0, 1], [1, 0], [1, 1]]], "port_regions": []},
        "new": {"regions": [], "port_regions": []},
        "matches": [], "splits": [], "merges": [], "disappeared": [0], "born": [],
    },
    "saddle": {
        "old": {"regions": [[[0, 0], [1, 1]]], "port_regions": [[0, 0], [0, 0]]},
        "new": {"regions": [[[0, 0]], [[1, 1]]], "port_regions": [[0, 0], [1, 1]]},
        "matches": [[0, 0], [0, 1]], "splits": [0], "merges": [], "disappeared": [], "born": [],
    },
}


def carriers(case, freeze):
    with closing(sqlite3.connect(":memory:")) as connection:
        intake, archive = IntakeStore(connection), ArchiveStore(connection)
        intake.initialize()
        archive.initialize()
        old_grid, new_grid = CASES[case]
        old_id = ingest_grid(intake, case, old_grid)
        new_id = ingest_grid(intake, case, new_grid, predecessor=old_id)
        artifact_ids = [freeze(intake, archive, revision, "1/2")
                        for revision in (old_id, new_id)]
        for revision in (old_id, new_id):
            disable_source(intake, revision)
        return tuple(pickup_artifact(archive, item) for item in artifact_ids)


def v1_carriers(case):
    return carriers(case, freeze_contour)


def v2_carriers(case):
    return carriers(case, freeze_hotspots)


def compare_summary(result):
    return {
        "old": {"regions": result["old"]["regions"],
                "port_regions": result["old"]["port_regions"]},
        "new": {"regions": result["new"]["regions"],
                "port_regions": result["new"]["port_regions"]},
        "matches": result["matches"], "splits": result["splits"], "merges": result["merges"],
        "disappeared": result["disappeared"], "born": result["born"],
    }


def check_compare(case):
    old_carrier, new_carrier = v2_carriers(case)
    forward = compare_summary(compare_hotspots(old_carrier, new_carrier))
    if forward != COMPARE_EXPECTED[case]:
        raise AssertionError(f"{case}: unexpected compare result: {forward}")
    if case == "split":
        swapped = compare_summary(compare_hotspots(new_carrier, old_carrier))
        expected = {
            "old": COMPARE_EXPECTED["split"]["new"],
            "new": COMPARE_EXPECTED["split"]["old"],
            "matches": [[0, 0], [1, 0]], "splits": [], "merges": [0],
            "disappeared": [], "born": [],
        }
        if swapped != expected:
            raise AssertionError(f"split reversed: unexpected compare result: {swapped}")
    return forward


def main():
    expected = {
        "opposite": ((('NESW',), ('NESW',)), (1, 1)),
        "uniform": (((), ()), (0, 0)),
        "saddle": ((('NE', 'SW'), ('NW', 'ES')), (2, 2)),
    }
    for case, (expected_sides, expected_counts) in expected.items():
        pair = v1_carriers(case)
        tables = tuple(decode_artifact(carrier).evidence.sections for carrier in pair)
        sides = tuple(tuple("".join(section.sides) for section in table) for table in tables)
        counts = tuple(len(audit_contour(carrier).components) for carrier in pair)
        if (sides, counts) != (expected_sides, expected_counts):
            raise AssertionError(f"{case}: unexpected V1 sections or line count: {(sides, counts)}")
        same_sections = tables[0] == tables[1]
        if same_sections != (case in ("opposite", "uniform")):
            raise AssertionError(f"{case}: unexpected V1 section equality")
        print(json.dumps({"case": case, "sections": sides, "line_counts": counts,
                          "same_sections": same_sections}, sort_keys=True))
    for case in ("opposite", "split", "cross", "uniform", "saddle"):
        summary = check_compare(case)
        print(json.dumps({"case": case, "compare": summary}, sort_keys=True))


if __name__ == "__main__":
    main()
