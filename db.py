from __future__ import annotations

import json
from datetime import datetime

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS debates (
    id              TEXT PRIMARY KEY,
    topic           TEXT NOT NULL,
    num_rounds      INTEGER NOT NULL,
    debater_models  TEXT NOT NULL,
    facilitator_model TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    debate_id   TEXT NOT NULL REFERENCES debates(id),
    seq         INTEGER NOT NULL,
    type        TEXT NOT NULL,
    speaker     TEXT,
    display_name TEXT,
    content     TEXT,
    round       INTEGER,
    UNIQUE(debate_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_debate_id ON messages(debate_id);
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(_SCHEMA)
    await db.commit()
    return db


async def save_debate(
    db: aiosqlite.Connection,
    debate_id: str,
    topic: str,
    num_rounds: int,
    debater_models: list[dict],
    facilitator_model: dict,
    events: list[dict],
    created_at: str | None = None,
) -> None:
    now = created_at or datetime.utcnow().isoformat(timespec="seconds")
    await db.execute(
        "INSERT INTO debates (id, topic, num_rounds, debater_models, facilitator_model, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            debate_id,
            topic,
            num_rounds,
            json.dumps(debater_models, ensure_ascii=False),
            json.dumps(facilitator_model, ensure_ascii=False),
            now,
        ),
    )
    for seq, event in enumerate(events):
        await db.execute(
            "INSERT INTO messages (debate_id, seq, type, speaker, display_name, content, round) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                debate_id,
                seq,
                event.get("type"),
                event.get("speaker"),
                event.get("display_name"),
                event.get("content"),
                event.get("round"),
            ),
        )
    await db.commit()


async def list_debates(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT id, topic, num_rounds, debater_models, created_at "
        "FROM debates ORDER BY created_at DESC LIMIT 100"
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row[0],
            "topic": row[1],
            "num_rounds": row[2],
            "debater_models": json.loads(row[3]),
            "created_at": row[4],
        }
        for row in rows
    ]


async def get_debate(db: aiosqlite.Connection, debate_id: str) -> dict | None:
    cursor = await db.execute(
        "SELECT id, topic, num_rounds, debater_models, facilitator_model, created_at "
        "FROM debates WHERE id = ?",
        (debate_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    cursor = await db.execute(
        "SELECT type, speaker, display_name, content, round "
        "FROM messages WHERE debate_id = ? ORDER BY seq ASC",
        (debate_id,),
    )
    msg_rows = await cursor.fetchall()
    events = [
        {
            "type": r[0],
            "speaker": r[1],
            "display_name": r[2],
            "content": r[3],
            "round": r[4],
        }
        for r in msg_rows
    ]

    return {
        "id": row[0],
        "topic": row[1],
        "num_rounds": row[2],
        "debater_models": json.loads(row[3]),
        "facilitator_model": json.loads(row[4]),
        "created_at": row[5],
        "events": events,
    }


async def export_debate_markdown(db: aiosqlite.Connection, debate_id: str) -> str | None:
    debate = await get_debate(db, debate_id)
    if debate is None:
        return None

    debater_names = ", ".join(d["name"] for d in debate["debater_models"])
    lines = [
        f"# {debate['topic']}",
        "",
        f"**日時:** {debate['created_at']}  ",
        f"**参加者:** {debater_names}  ",
        f"**ラウンド数:** {debate['num_rounds']}",
        "",
        "---",
        "",
    ]

    current_round = None
    for event in debate["events"]:
        t = event["type"]
        if t == "round_start":
            current_round = event["round"]
            lines.append(f"## ラウンド {current_round}")
            lines.append("")
        elif t == "message":
            if event.get("round", 0) == 0:
                lines.append("## 開会")
                lines.append("")
            lines.append(f"### {event['display_name']}")
            lines.append("")
            lines.append(event.get("content") or "")
            lines.append("")
        elif t == "conclusion":
            lines.append("## 結論")
            lines.append("")
            lines.append(event.get("content") or "")
            lines.append("")

    return "\n".join(lines)
