from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Self

from blessed import Terminal


def write(*args: object) -> None:
    """Wrapper over the `print` function that sets the `end` argument to `None`
    and flushes the buffer immediately."""

    print(*args, end="", flush=True)


@dataclass
class Canvas:
    blocks: set[tuple[int, int]] = field(default_factory=set)
    size: tuple[int, int] = (50, 20)
    cursor: tuple[int, int] = (0, 0)

    def move_cursor(self, dx: int, dy: int) -> set[tuple[int, int]]:
        """Move the cursor by the given offsets, clamping the result within the
        canvas bounds.

        Returns:
            A set of positions that should be rerendered after the update.
        """

        width, height = self.size
        x, y = self.cursor
        new_x = max(0, min(width - 1, x + dx))
        new_y = max(0, min(height - 1, y + dy))
        self.cursor = (new_x, new_y)

        if (x, y) != self.cursor:
            return set([(x, y), self.cursor])
        else:
            return set()

    def toggle_block(self) -> set[tuple[int, int]]:
        """Toggles the block pointed by the cursor.

        Returns:
            A set of positions that should be rerendered after the update."""

        if self.cursor in self.blocks:
            self.blocks.remove(self.cursor)
        else:
            self.blocks.add(self.cursor)

        return set([self.cursor])


class CanvasController:
    """Manages a printable canvas in a terminal window.

    Canvas can be controlled by a user through the following actions:

    - 'w': Move the cursor up.
    - 'd': Move the cursor to the right.
    - 's': Move the cursor down.
    - 'a': Move the cursor to the left.
    - ' ' (space): Toggles a block at the current cursor position.
    """

    def __init__(
        self,
        *,
        term: Terminal = Terminal(),
        canvas: Canvas = Canvas(blocks=set()),
        cursor="█",
        block="█",
    ) -> None:
        self._stack = ExitStack()
        self.term = term
        self.canvas = canvas
        self.cursor = cursor
        self.block = block
        self._quitting = False

    def __enter__(self) -> Self:
        self._stack.enter_context(self.term.cbreak())
        self._stack.enter_context(self.term.hidden_cursor())
        return self

    def __exit__(self, *args: any) -> None:
        self._stack.close()

    def start(self) -> None:
        """Starts an event loop, handles user input and updates the canvas until
        user requests to close the program."""

        write(self.term.clear)

        # Show the cursor before the first user keypress
        self._render(set([self.canvas.cursor]))

        while not self._quitting:
            self.update()

    def update(self) -> None:
        """Updates the canvas state based on user's input and rerenders it."""

        key = self.term.inkey()

        if key == "q":
            self._quitting = True
            return

        updates = self._update_cursor(key)
        updates = updates.union(self._update_blocks(key))
        self._render(updates)

    def _update_cursor(self, key: str) -> set[tuple[int, int]]:
        """Updates the cursor position if the key is one of the movement keys.

        Returns:
            A set of updated positions."""

        velocity = (0, 0)
        match key:
            case "w":
                velocity = (0, -1)
            case "s":
                velocity = (0, 1)
            case "a":
                velocity = (-1, 0)
            case "d":
                velocity = (1, 0)

        return self.canvas.move_cursor(*velocity)

    def _update_blocks(self, key: str) -> set[tuple[int, int]]:
        """Toggles a block if user pressed the space key.

        Returns:
            A set of updated positions."""

        if key != " ":
            return set()

        return self.canvas.toggle_block()

    def _render(self, positions: set[tuple[int, int]]) -> None:
        """Renders the specified set of positions."""

        seq = ""
        for x, y in positions:
            seq += self._render_sequence(x, y)
        write(seq)

    def _render_sequence(self, x: int, y: int) -> str:
        """Creates a render sequence for the specified point."""

        if self.canvas.cursor == (x, y):
            return self.term.move_xy(x, y) + self.term.blink(self.cursor)
        elif (x, y) in self.canvas.blocks:
            return self.term.move_xy(x, y) + self.term.teal(self.block)
        else:
            return self.term.move_xy(x, y) + " "


def main() -> None:
    with CanvasController() as canvas:
        canvas.start()
