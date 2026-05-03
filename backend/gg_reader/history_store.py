from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import GgTableSnapshot


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
HISTORY_PATH = DATA_DIR / "gg_history.jsonl"
DB_PATH = DATA_DIR / "gg_history.sqlite"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    _init_db(connection)
    return connection


def _init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS gg_hands (
            hand_id TEXT PRIMARY KEY,
            started_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            table_type TEXT NOT NULL,
            first_snapshot_json TEXT NOT NULL,
            latest_snapshot_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gg_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            street TEXT NOT NULL,
            pot REAL NOT NULL,
            dealer_seat_index INTEGER NOT NULL,
            active_player_count INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            FOREIGN KEY(hand_id) REFERENCES gg_hands(hand_id)
        );

        CREATE TABLE IF NOT EXISTS gg_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id TEXT,
            time INTEGER NOT NULL,
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_gg_snapshots_hand_time ON gg_snapshots(hand_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_gg_events_hand_time ON gg_events(hand_id, time);
        """
    )
    connection.commit()


def append_event(event: dict[str, Any]) -> None:
    normalized = {
        "time": int(event.get("time") or event.get("timestamp") or 0),
        "type": str(event.get("type") or "event"),
        "message": str(event.get("message") or ""),
        "handId": event.get("handId"),
        "data": event.get("data") or {},
    }
    if normalized["time"] <= 0:
        import time

        normalized["time"] = int(time.time() * 1000)
    _append_jsonl(normalized)
    with _connect() as connection:
        _insert_event(connection, normalized)
        connection.commit()


def record_snapshot(snapshot: GgTableSnapshot, previous: GgTableSnapshot | None = None) -> list[dict[str, Any]]:
    snapshot_data = snapshot.model_dump(mode="json")
    snapshot_json = json.dumps(snapshot_data, ensure_ascii=False, separators=(",", ":"))
    hand_id = snapshot.handId or f"hand-{snapshot.timestamp}"
    events = build_snapshot_events(snapshot, previous)

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO gg_hands(hand_id, started_at, updated_at, table_type, first_snapshot_json, latest_snapshot_json)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(hand_id) DO UPDATE SET
                updated_at=excluded.updated_at,
                latest_snapshot_json=excluded.latest_snapshot_json
            """,
            (
                hand_id,
                snapshot.timestamp,
                snapshot.timestamp,
                snapshot.tableType,
                snapshot_json,
                snapshot_json,
            ),
        )
        connection.execute(
            """
            INSERT INTO gg_snapshots(hand_id, timestamp, street, pot, dealer_seat_index, active_player_count, snapshot_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hand_id,
                snapshot.timestamp,
                snapshot.street,
                float(snapshot.pot or 0),
                int(snapshot.dealerSeatIndex or 0),
                int(snapshot.activePlayerCount or 0),
                snapshot_json,
            ),
        )
        for event in events:
            _insert_event(connection, event)
            _append_jsonl(event)
        connection.commit()
    return events


def build_snapshot_events(snapshot: GgTableSnapshot, previous: GgTableSnapshot | None = None) -> list[dict[str, Any]]:
    hand_id = snapshot.handId
    now = snapshot.timestamp
    events: list[dict[str, Any]] = []

    def add(event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        events.append({
            "time": now,
            "type": event_type,
            "message": message,
            "handId": hand_id,
            "data": data or {},
        })

    if previous is None or previous.handId != snapshot.handId:
        add("hand_started", "יד חדשה נקלטה מ-GG", snapshot.model_dump(mode="json"))
        return events

    if previous.street != snapshot.street:
        add("street_changed", f"רחוב השתנה ל-{snapshot.street}", {"from": previous.street, "to": snapshot.street})
    if round(float(previous.pot or 0), 2) != round(float(snapshot.pot or 0), 2):
        add("pot_changed", f"קופה: {float(snapshot.pot or 0):g} BB", {"from": previous.pot, "to": snapshot.pot})
    if previous.dealerSeatIndex != snapshot.dealerSeatIndex:
        add("dealer_changed", f"דילר עבר למושב {snapshot.dealerSeatIndex + 1}", {"to": snapshot.dealerSeatIndex})
    if previous.activePlayerCount != snapshot.activePlayerCount:
        add(
            "active_player_count_changed",
            f"מספר שחקנים פעילים: {snapshot.activePlayerCount}",
            {"from": previous.activePlayerCount, "to": snapshot.activePlayerCount},
        )

    previous_board = {_card_id(card) for card in previous.board if _card_id(card)}
    for card in snapshot.board:
        card_id = _card_id(card)
        if card_id and card_id not in previous_board:
            add("board_card_added", f"קלף board נוסף: {card_id}", card.model_dump(mode="json"))

    previous_seats = {seat.physicalSeatIndex: seat for seat in previous.seats}
    for seat in snapshot.seats:
        before = previous_seats.get(seat.physicalSeatIndex)
        seat_name = seat.name or f"מושב {seat.physicalSeatIndex + 1}"
        if before is None or before.active is False:
            if seat.active:
                add("player_joined", f"{seat_name} נכנס", seat.model_dump(mode="json"))
            continue
        if before.active and not seat.active:
            add("player_left", f"{before.name or seat_name} יצא", seat.model_dump(mode="json"))
        if (before.name or "") != (seat.name or "") and seat.name:
            add("player_name_changed", f"מושב {seat.physicalSeatIndex + 1}: {seat.name}", {"from": before.name, "to": seat.name})
        if (before.position or "") != (seat.position or "") and seat.position:
            add("position_changed", f"{seat_name}: {seat.position}", {"from": before.position, "to": seat.position})
        if round(float(before.stack or 0), 2) != round(float(seat.stack or 0), 2):
            add("stack_changed", f"{seat_name}: {float(seat.stack or 0):g} BB", {"from": before.stack, "to": seat.stack})
        if round(float(before.currentBet or 0), 2) != round(float(seat.currentBet or 0), 2):
            add("bet_changed", f"{seat_name}: הימור {float(seat.currentBet or 0):g} BB", {"from": before.currentBet, "to": seat.currentBet})
        if before.action != seat.action and seat.action != "none":
            add("player_action", f"{seat_name}: {_action_label(seat.action)}", seat.model_dump(mode="json"))
        if before.status != seat.status and seat.status == "folded":
            add("player_folded", f"{seat_name}: פולד", seat.model_dump(mode="json"))
    return events


def read_history(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT hand_id, time, type, message, data_json
            FROM gg_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [
        {
            "handId": row["hand_id"],
            "time": row["time"],
            "type": row["type"],
            "message": row["message"],
            "data": json.loads(row["data_json"] or "{}"),
        }
        for row in rows
    ]


def read_hands(limit: int = 25) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT hand_id, started_at, updated_at, table_type, latest_snapshot_json
            FROM gg_hands
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [
        {
            "handId": row["hand_id"],
            "startedAt": row["started_at"],
            "updatedAt": row["updated_at"],
            "tableType": row["table_type"],
            "latestSnapshot": json.loads(row["latest_snapshot_json"]),
        }
        for row in rows
    ]


def _insert_event(connection: sqlite3.Connection, event: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO gg_events(hand_id, time, type, message, data_json)
        VALUES(?, ?, ?, ?, ?)
        """,
        (
            event.get("handId"),
            int(event.get("time") or 0),
            str(event.get("type") or "event"),
            str(event.get("message") or ""),
            json.dumps(event.get("data") or {}, ensure_ascii=False, separators=(",", ":")),
        ),
    )


def _append_jsonl(event: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _card_id(card: Any) -> str:
    if not card or getattr(card, "hidden", False) or not getattr(card, "rank", None) or not getattr(card, "suit", None):
        return ""
    return f"{card.rank}{card.suit}".upper()


def _action_label(action: str) -> str:
    return {
        "check": "צ'ק",
        "call": "קול",
        "bet": "הימור",
        "raise": "רייז",
        "fold": "פולד",
        "all-in": "אול אין",
        "waiting": "ממתין",
    }.get(action, action)
