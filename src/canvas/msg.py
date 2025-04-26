from typing import Literal, Union

from pydantic import BaseModel, TypeAdapter


class BlockPlacedMessage(BaseModel):
    """A message for placing a block on a canvas."""

    type: Literal["block-placed"] = "block-placed"
    x: int
    y: int


class BlockRemovedMessage(BaseModel):
    """A message for removing a block from a canvas."""

    type: Literal["block-removed"] = "block-removed"
    x: int
    y: int


Message = Union[BlockPlacedMessage, BlockRemovedMessage]

message_adapter = TypeAdapter(Message)
