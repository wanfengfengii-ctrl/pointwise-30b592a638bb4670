from freeze.edge_crossings import edge_crossings
from freeze.evidence import EDGE_ORDER, CellSection


def classify_cell(
    row: int, col: int, corners: tuple[int, int, int, int], threshold2: int
) -> tuple[CellSection, ...]:
    crossings = edge_crossings(row, col, corners, threshold2)
    if not crossings:
        return ()

    if len(crossings) == 2:
        groups = (tuple(side for side in EDGE_ORDER if side in crossings),)
    else:
        a, b, c, d = (2 * temperature - threshold2 for temperature in corners)
        # The determinant of the signed corner values distinguishes the saddle cases.
        determinant = a * d - b * c
        if determinant == 0:
            groups = (EDGE_ORDER,)
        elif determinant < 0:
            groups = (('N', 'W'), ('E', 'S'))
        else:
            groups = (('N', 'E'), ('S', 'W'))

    return tuple(
        CellSection(row, col, tuple((side, crossings[side]) for side in group))
        for group in groups
    )
