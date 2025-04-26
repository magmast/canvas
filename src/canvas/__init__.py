import asyncio
import os
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Self

from blessed import Terminal
from dotenv import load_dotenv
from pubnub.models.consumer.pubsub import PNMessageResult
from pubnub.pnconfiguration import PNConfiguration
from pubnub.pubnub import PubNub

from .msg import BlockPlacedMessage, BlockRemovedMessage, Message, message_adapter

load_dotenv()

PUBNUB_PUBLISH_KEY = os.getenv("PUBNUB_PUBLISH_KEY")
assert PUBNUB_PUBLISH_KEY is not None

PUBNUB_SUBSCRIBE_KEY = os.getenv("PUBNUB_SUBSCRIBE_KEY")
assert PUBNUB_SUBSCRIBE_KEY is not None

PUBNUB_CHANNEL_NAME = "messages"


@dataclass
class Canvas:
    blocks: set[tuple[int, int]] = field(default_factory=set)

    def toggle_block(self, x: int, y: int) -> BlockPlacedMessage | BlockRemovedMessage:
        """
        Toggles the block at the specified coordinates.

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
    """
    Wrapper over the `print` function that sets the `end` argument to `None`
    and flushes the buffer immediately.
    """
    print(*args, end="", flush=True)


class BlessedChannel(Channel):
    """Channel that reads and writes to a user terminal window."""

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
        self._executor = ThreadPoolExecutor()
        self._canvas = Canvas()
        self._closed = False
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
        if self._closed:
            return None

        while True:
            try:
                key = await asyncio.get_event_loop().run_in_executor(
                    self._executor, lambda: self.term.inkey()
                )
            except asyncio.CancelledError:
                continue

            if key == "q":
                self._closed = True
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


class PubNubChannel(Channel):
    """Channel that reads and writes messages to a PubNub channel."""

    def __init__(self):
        config = PNConfiguration()
        config.subscribe_key = PUBNUB_SUBSCRIBE_KEY
        config.publish_key = PUBNUB_PUBLISH_KEY
        config.ssl = True
        config.enable_subscribe = True
        config.daemon = True
        config.user_id = str(uuid.uuid4())

        self.pubnub = PubNub(config)
        self.user_id = config.user_id
        self.queue: list[Message] = []

    def __enter__(self) -> Self:
        subscription = self.pubnub.channel(PUBNUB_CHANNEL_NAME).subscription()
        subscription.on_message = self._handle_message
        subscription.subscribe()
        return self

    def __exit__(self, *args):
        self.pubnub.stop()

    async def write(self, msg):
        data = message_adapter.dump_python(msg)
        self.pubnub.publish().channel(PUBNUB_CHANNEL_NAME).message(data).sync()

    async def read(self):
        while not self.queue:
            await asyncio.sleep(1 / 60)
        msgs = self.queue
        self.queue = []
        return msgs

    def _handle_message(self, result: PNMessageResult) -> None:
        if result.publisher == self.user_id:
            return
        msg = message_adapter.validate_python(result.message)
        self.queue.append(msg)


async def _race(channels: list[Channel]) -> tuple[Channel, list[Message] | None]:
    """
    Waits for the first message to be received from any of the given channels.
    This asynchronous function concurrently reads from multiple channels and
    returns as soon as the first message is received from any channel. It
    cancels all other pending read operations once a message is received.
    """

    tasks = {asyncio.create_task(ch.read()): ch for ch in channels}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    done_task = done.pop()
    msgs = await done_task
    sender = tasks[done_task]
    return sender, msgs


async def _forward(channels: list[Channel], sender: Channel, msgs: list[Message]):
    for ch in channels:
        if ch is sender:
            continue
        for msg in msgs:
            asyncio.create_task(ch.write(msg))


async def _run() -> None:
    with BlessedChannel() as blessed, PubNubChannel() as pubnub:
        channels: list[Channel] = [blessed, pubnub]
        while True:
            sender, msgs = await _race(channels)
            if msgs is None:
                break
            await _forward(channels, sender, msgs)


def main() -> None:
    asyncio.run(_run())
