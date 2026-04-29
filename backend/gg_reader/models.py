from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Street = Literal["preflop", "flop", "turn", "river", "showdown", "unknown"]


class GgReaderStartRequest(BaseModel):
    monitorIndex: int = 2
    fps: float = Field(default=2, ge=0.2, le=10)
    profile: str = "ggclub_9max"
    debug: bool = False


class GgCard(BaseModel):
    rank: str | None = None
    suit: str | None = None
    visible: bool = True
    hidden: bool = False
    display: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)


class GgSeat(BaseModel):
    physicalSeatIndex: int
    active: bool = True
    name: str | None = None
    stack: float = 0
    currentBet: float = 0
    committed: float = 0
    position: str | None = None
    isDealer: bool = False
    isHero: bool = False
    holeCards: list[GgCard] = Field(default_factory=list)
    confidence: float = Field(default=1, ge=0, le=1)


class GgTableSnapshot(BaseModel):
    source: Literal["ggclub"] = "ggclub"
    timestamp: int
    tableType: str = "9max"
    handId: str | None = None
    street: Street = "unknown"
    pot: float = 0
    dealerSeatIndex: int = 0
    heroSeatIndex: int | None = None
    board: list[GgCard] = Field(default_factory=list)
    seats: list[GgSeat] = Field(default_factory=list)
    confidence: float = Field(default=1, ge=0, le=1)


class GgReaderStatus(BaseModel):
    running: bool = False
    monitorIndex: int = 2
    fps: float = 2
    profile: str = "ggclub_9max"
    message: str = "idle"
    lastSnapshotAt: int | None = None
