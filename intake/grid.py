from dataclasses import dataclass


@dataclass(frozen=True)
class Grid:
    vertices: tuple[tuple[int, ...], ...]

    @property
    def cell_shape(self) -> tuple[int, int]:
        return len(self.vertices) - 1, len(self.vertices[0]) - 1

    def cell_corners(self, row: int, col: int) -> tuple[int, int, int, int]:
        rows, cols = self.cell_shape
        if type(row) is not int or type(col) is not int:
            raise ValueError('cell coordinates must be integers')
        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError('cell is outside the grid')
        north, south = self.vertices[row], self.vertices[row + 1]
        return north[col], north[col + 1], south[col], south[col + 1]


def parse_grid(raw: object) -> Grid:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ValueError('grid requires at least two vertex rows')

    rows = []
    width = None
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValueError('each vertex row requires at least two values')
        if width is None:
            width = len(row)
        if len(row) != width:
            raise ValueError('grid must be rectangular')
        if any(type(temperature) is not int for temperature in row):
            raise ValueError('vertex temperatures must be integers')
        rows.append(tuple(row))
    return Grid(tuple(rows))
