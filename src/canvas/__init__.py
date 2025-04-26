import asyncio
from abc import ABC, abstractmethod
from asyncio import TaskGroup
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Self

from blessed import Terminal

from .msg import (
    BlockPlacedMessage,
    BlockRemovedMessage,
    Message,
)


@dataclass
class Canvas:
    blocks: set[tuple[int, int]] = field(default_factory=set)

    def toggle_block(self, x: int, y: int) -> BlockPlacedMessage | BlockRemovedMessage:
        """Toggles the block at the specified coordinates.

        Returns:
            A message representing the update.
        """

        if (x, y) in self.blocks:
            self.blocks.remove((x, y))
            return BlockRemovedMessage(x=x, y=y)

        self.blocks.add((x, y))
        return BlockPlacedMessage(x=x, y=y)

    def add_block(self, x: int, y: int) -> None:
        """Marks the block at the coordinates as painted."""
        self.blocks.add((x, y))

    def remove_block(self, x: int, y: int) -> None:
        """Removes the block at the coordinates from painted blocks."""
        self.blocks.remove((x, y))


class Channel(ABC):
    @abstractmethod
    async def read(self) -> list[Message] | None:
        """Reads all queued messages from the channel.

        Returns:
            A list of queued messages or None if the channel is closed.
        """

    @abstractmethod
    async def write(self, msg: Message) -> None:
        """Writes the message to the channel."""


def write(*args: object) -> None:
    """Wrapper over the `print` function that sets the `end` argument to `None`
    and flushes the buffer immediately."""
    print(*args, end="", flush=True)


class BlessedCommandChannel(Channel):
    def __init__(
        self,
        *,
        term: Terminal | None = None,
        width=50,
        height=20,
        cursor="█",
        block="█",
    ):
        self._stack = ExitStack()
        self._executor = ThreadPoolExecutor(1)
        self._canvas = Canvas()
        self.term = term if term is not None else Terminal()
        self.width = width
        self.height = height
        self.cursor_ch = cursor
        self.block_ch = block
        self.x = 0
        self.y = 0

    def __enter__(self) -> Self:
        self._stack.enter_context(self.term.cbreak())
        self._stack.enter_context(self.term.hidden_cursor())
        write(self.term.clear)
        self._render((self.x, self.y))
        return self

    def __exit__(self, *args):
        self._stack.close()

    async def read(self):
        while True:
            key = await asyncio.get_event_loop().run_in_executor(
                self._executor, lambda: self.term.inkey()
            )
            if key == "q":
                return None

            cmd = self._handle_key(key)
            if cmd != None:
                return [cmd]

    def _handle_key(self, key: str) -> Message | None:
        match key:
            case " ":
                return self._canvas.toggle_block(self.x, self.y)
            case "w":
                self._move_cursor(0, -1)
            case "d":
                self._move_cursor(1, 0)
            case "s":
                self._move_cursor(0, 1)
            case "a":
                self._move_cursor(-1, 0)

    def _move_cursor(self, dx: int, dy: int) -> None:
        prev_x, prev_y = self.x, self.y
        self.x = max(0, min(self.width - 1, prev_x + dx))
        self.y = max(0, min(self.height - 1, prev_y + dy))
        if prev_x != self.x or prev_y != self.y:
            self._render((prev_x, prev_y), (self.x, self.y))

    async def write(self, event):
        match event:
            case BlockPlacedMessage(x=x, y=y):
                self._canvas.add_block(x, y)
                self._render((x, y))
            case BlockRemovedMessage(x=x, y=y):
                self._canvas.remove_block(x, y)
                self._render((x, y))

    def _render(self, *positions: tuple[int, int]) -> None:
        seq = ""
        for pos in positions:
            seq += self.term.move_xy(*pos) + self._char_at(*pos)
        write(seq)

    def _char_at(self, x: int, y: int) -> str:
        if self.x == x and self.y == y:
            return self.term.blink(self.cursor_ch)
        elif (x, y) in self._canvas.blocks:
            return self.term.teal(self.block_ch)
        else:
            return " "


async def run() -> None:
    with BlessedCommandChannel() as channel:
        while True:
            events = await channel.read()
            if events is None:
                break

            async with TaskGroup() as group:
                for event in events:
                    group.create_task(channel.write(event))


def main() -> None:
    asyncio.run(run())
