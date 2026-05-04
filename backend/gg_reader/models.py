from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Street = Literal["preflop", "flop", "turn", "river", "showdown", "unknown"]
SeatAction = Literal["none", "check", "call", "bet", "raise", "fold", "all-in", "waiting"]
SeatStatus = Literal["empty", "active", "folded", "sitting_out", "unknown"]


class GgReaderStartRequest(BaseModel):
    monitorIndex: int = 2
    fps: float = Field(default=2, ge=0.2, le=10)
    profile: str = "ggclub_9max"
    debug: bool = False
    captureMode: Literal["auto", "window", "monitor", "browser"] = "auto"


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
    nameConfidence: float | None = Field(default=None, ge=0, le=1)
    stack: float = 0
    stackConfidence: float | None = Field(default=None, ge=0, le=1)
    currentBet: float = 0
    betConfidence: float | None = Field(default=None, ge=0, le=1)
    committed: float = 0
    position: str | None = None
    action: SeatAction = "none"
    actionAmount: float = 0
    actionConfidence: float | None = Field(default=None, ge=0, le=1)
    status: SeatStatus = "active"
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
    smallBlind: float = 0.5
    activePlayerCount: int = 0
    bigBlind: float = 1
    dealerSeatIndex: int = 0
    heroSeatIndex: int | None = None
    board: list[GgCard] = Field(default_factory=list)
    seats: list[GgSeat] = Field(default_factory=list)
    confidence: float = Field(default=1, ge=0, le=1)
    metrics: dict[str, Any] = Field(default_factory=dict)


class GgReaderStatus(BaseModel):
    running: bool = False
    monitorIndex: int = 2
    fps: float = 2
    profile: str = "ggclub_9max"
    message: str = "idle"
    lastSnapshotAt: int | None = None
    framesRead: int = 0
    lastFrameMs: float | None = None
    captureSource: str | None = None
