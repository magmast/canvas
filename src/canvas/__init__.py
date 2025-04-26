from contextlib import ExitStack
from typing import Self

from blessed import Terminal


def write(*args: object) -> None:
    """Wrapper over the `print` function that sets the `end` argument to `None` and flushes the buffer immediately."""

    print(*args, end="", flush=True)


class CanvasController:
    """Manages a printable canvas in a terminal window.

    Canvas can be controlled by the user through the following list of actions:

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
        width: int = 50,
        height: int = 20,
        cursor="█",
        block="█",
    ) -> None:
        self._stack = ExitStack()
        self.term = term
        self.width = width
        self.height = height
        self.cursor = cursor
        self.block = block
        self._quitting = False
        self.x = 0
        self.y = 0
        self.blocks: set[tuple[int, int]] = set()
        self.updates: list[tuple[int, int]] = []

    def __enter__(self) -> Self:
        self._stack.enter_context(self.term.cbreak())
        self._stack.enter_context(self.term.hidden_cursor())
        write(self.term.home + self.term.clear)
        return self

    def __exit__(self, *args: any) -> None:
        self._stack.close()

    def start(self) -> None:
        """Starts an event loop, handles user input and updates the canvas until user requests to close the program."""

        # Show the cursor before the first user keypress
        self._queue(self.x, self.y)
        self._flush()

        while not self._quitting:
            self.update()

    def update(self) -> None:
        """Updates the canvas state based on user's input and rerenders it."""

        key = self.term.inkey()

        if key == "q":
            self._quitting = True
            return

        self._update_cursor(key)
        self._update_blocks(key)
        self._flush()

    def _update_cursor(self, key: str) -> None:
        """Modifies the cursor position and queues the cursor render according to the pressed key."""

        velocity = (0, 0)
        if self.y > 0 and key == "w":
            velocity = (0, -1)
        if self.y < self.height - 1 and key == "s":
            velocity = (0, 1)
        if self.x > 0 and key == "a":
            velocity = (-1, 0)
        if self.x < self.width - 1 and key == "d":
            velocity = (1, 0)

        if velocity[0] != 0 or velocity[1] != 0:
            prev_x = self.x
            prev_y = self.y
            self.x += velocity[0]
            self.y += velocity[1]
            self._queue(prev_x, prev_y)
            self._queue(self.x, self.y)

    def _update_blocks(self, key: str) -> None:
        """Checks if the pressed key is the key that toggles a block, updates the blocks array accordingly and queues a render of the block."""

        if key != " ":
            return

        pos = (self.x, self.y)
        if pos in self.blocks:
            self.blocks.remove(pos)
        else:
            self.blocks.add(pos)

        self._queue(self.x, self.y)

    def _queue(self, x: int, y: int) -> None:
        """Queues an update of the character at the specified coordinates."""

        self.updates.append((x, y))

    def _flush(self) -> None:
        """Writes all queued updates to the stdout and the queue."""

        seq = ""
        for x, y in self.updates:
            seq += self._point_sequence(x, y)
        write(seq)

        self.updates = []

    def _point_sequence(self, x: int, y: int) -> str:
        """Generates a render sequence for the specified point."""

        if self.x == x and self.y == y:
            return self.term.move_xy(x, y) + self.term.blink(self.cursor)
        elif (x, y) in self.blocks:
            return self.term.move_xy(x, y) + self.term.teal(self.block)
        else:
            return self.term.move_xy(x, y) + " "


def main() -> None:
    with CanvasController() as canvas:
        canvas.start()
