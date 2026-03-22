from __future__ import annotations

import pytest
import pytest_asyncio

from db import init_db, save_debate, list_debates, get_debate, export_debate_markdown


SAMPLE_EVENTS = [
    {"type": "message", "speaker": "facilitator", "display_name": "Facilitator", "content": "議論を始めます。", "round": 0},
    {"type": "round_start", "round": 1},
    {"type": "message", "speaker": "Alice", "display_name": "Alice", "content": "Aliceの意見です。", "round": 1},
    {"type": "message", "speaker": "Bob", "display_name": "Bob", "content": "Bobの意見です。", "round": 1},
    {"type": "generating_conclusion"},
    {"type": "conclusion", "speaker": "facilitator", "display_name": "Facilitator", "content": "結論です。"},
    {"type": "done"},
]

DEBATER_MODELS = [
    {"model": "anthropic/claude-sonnet-4-6", "name": "Alice"},
    {"model": "openai/gpt-4o", "name": "Bob"},
]

FACILITATOR_MODEL = {"model": "anthropic/claude-sonnet-4-6", "name": "Facilitator"}


@pytest_asyncio.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await conn.close()


async def _save_sample(db, debate_id="test123", topic="テストのお題", created_at=None):
    await save_debate(
        db=db,
        debate_id=debate_id,
        topic=topic,
        num_rounds=1,
        debater_models=DEBATER_MODELS,
        facilitator_model=FACILITATOR_MODEL,
        events=SAMPLE_EVENTS,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_init_db_creates_tables(db):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in await cursor.fetchall()]
    assert "debates" in tables
    assert "messages" in tables


@pytest.mark.asyncio
async def test_save_and_get_debate(db):
    await _save_sample(db)
    debate = await get_debate(db, "test123")

    assert debate is not None
    assert debate["id"] == "test123"
    assert debate["topic"] == "テストのお題"
    assert debate["num_rounds"] == 1
    assert len(debate["debater_models"]) == 2
    assert debate["debater_models"][0]["name"] == "Alice"
    assert debate["facilitator_model"]["name"] == "Facilitator"
    assert len(debate["events"]) == len(SAMPLE_EVENTS)


@pytest.mark.asyncio
async def test_events_ordering_preserved(db):
    await _save_sample(db)
    debate = await get_debate(db, "test123")

    types = [e["type"] for e in debate["events"]]
    expected = [e["type"] for e in SAMPLE_EVENTS]
    assert types == expected


@pytest.mark.asyncio
async def test_list_debates_ordering(db):
    await _save_sample(db, debate_id="first", topic="最初の議論", created_at="2025-01-01T00:00:00")
    await _save_sample(db, debate_id="second", topic="二番目の議論", created_at="2025-01-02T00:00:00")

    debates = await list_debates(db)
    assert len(debates) == 2
    # Most recent first
    assert debates[0]["id"] == "second"
    assert debates[1]["id"] == "first"


@pytest.mark.asyncio
async def test_list_debates_empty(db):
    debates = await list_debates(db)
    assert debates == []


@pytest.mark.asyncio
async def test_get_debate_not_found(db):
    result = await get_debate(db, "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_export_debate_markdown(db):
    await _save_sample(db)
    md = await export_debate_markdown(db, "test123")

    assert md is not None
    assert "# テストのお題" in md
    assert "Alice" in md
    assert "Bob" in md
    assert "## 結論" in md
    assert "結論です。" in md
    assert "## ラウンド 1" in md


@pytest.mark.asyncio
async def test_export_not_found(db):
    result = await export_debate_markdown(db, "nonexistent")
    assert result is None


SAMPLE_EVENTS_WITH_HUMAN = [
    {"type": "message", "speaker": "facilitator", "display_name": "Facilitator", "content": "議論を始めます。", "round": 0},
    {"type": "round_start", "round": 1},
    {"type": "message", "speaker": "Alice", "display_name": "Alice", "content": "Aliceの意見です。", "round": 1},
    {"type": "message", "speaker": "facilitator", "display_name": "Facilitator", "content": "要約です。", "round": 1},
    {"type": "message", "speaker": "human", "display_name": "Human", "content": "もっと具体例を。", "round": 1},
    {"type": "round_start", "round": 2},
    {"type": "message", "speaker": "Alice", "display_name": "Alice", "content": "Aliceの追加意見。", "round": 2},
    {"type": "generating_conclusion"},
    {"type": "conclusion", "speaker": "facilitator", "display_name": "Facilitator", "content": "結論です。"},
    {"type": "done"},
]


@pytest.mark.asyncio
async def test_save_and_get_debate_with_human_messages(db):
    await save_debate(
        db=db, debate_id="human_test", topic="介入テスト",
        num_rounds=2, debater_models=DEBATER_MODELS,
        facilitator_model=FACILITATOR_MODEL, events=SAMPLE_EVENTS_WITH_HUMAN,
    )
    debate = await get_debate(db, "human_test")
    human_msgs = [e for e in debate["events"] if e.get("speaker") == "human"]
    assert len(human_msgs) == 1
    assert human_msgs[0]["content"] == "もっと具体例を。"


@pytest.mark.asyncio
async def test_export_with_human_messages(db):
    await save_debate(
        db=db, debate_id="human_export", topic="介入テスト",
        num_rounds=2, debater_models=DEBATER_MODELS,
        facilitator_model=FACILITATOR_MODEL, events=SAMPLE_EVENTS_WITH_HUMAN,
    )
    md = await export_debate_markdown(db, "human_export")
    assert "ユーザー介入" in md
    assert "もっと具体例を。" in md
