from __future__ import annotations

import asyncio
import pytest

from debate import DebateManager


# --- Mock LLMClient ---


class MockLLMClient:
    """generate() が呼ばれるたびに call_count を記録し、定型文を返す。"""

    def __init__(self, display_name: str, response: str = ""):
        self.display_name = display_name
        self.name = display_name
        self.calls: list[tuple[str, str]] = []
        self._response = response or f"{display_name}の回答です。"

    async def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self._response


class FailingLLMClient(MockLLMClient):
    """最初の呼び出しだけ例外を投げ、以降は正常に返す。"""

    def __init__(self, display_name: str, fail_times: int = 1):
        super().__init__(display_name)
        self._fail_times = fail_times
        self._call_count = 0

    async def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        self.calls.append((system_prompt, user_prompt))
        self._call_count += 1
        if self._call_count <= self._fail_times:
            raise RuntimeError("API connection failed")
        return self._response


# --- Helpers ---


async def collect_events(manager: DebateManager) -> list[dict]:
    events = []
    async for event in manager.run():
        events.append(event)
    return events


def make_manager(
    num_debaters: int = 2,
    num_rounds: int = 2,
    debaters: dict = None,
    facilitator: MockLLMClient = None,
) -> DebateManager:
    if debaters is None:
        names = ["Alice", "Bob", "Carol", "Dave"][:num_debaters]
        debaters = {
            f"d{i}": MockLLMClient(name) for i, name in enumerate(names)
        }
    return DebateManager(
        topic="テストのお題",
        debaters=debaters,
        facilitator=facilitator or MockLLMClient("Facilitator"),
        num_rounds=num_rounds,
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_event_sequence_1_round():
    """1ラウンドの議論で正しいイベント順序になるか。"""
    manager = make_manager(num_debaters=2, num_rounds=1)
    events = await collect_events(manager)

    types = [e["type"] for e in events]
    # 開会 → round_start → debater×2 → conclusion → done
    assert types == [
        "message",      # facilitator opening
        "round_start",  # round 1
        "message",      # debater 1
        "message",      # debater 2
        "conclusion",
        "done",
    ]


@pytest.mark.asyncio
async def test_event_sequence_2_rounds():
    """2ラウンドではラウンド間にファシリテーター要約が入る。"""
    manager = make_manager(num_debaters=2, num_rounds=2)
    events = await collect_events(manager)

    types = [e["type"] for e in events]
    assert types == [
        "message",      # facilitator opening
        "round_start",  # round 1
        "message",      # debater 1
        "message",      # debater 2
        "message",      # facilitator summary
        "round_start",  # round 2
        "message",      # debater 1
        "message",      # debater 2
        "conclusion",
        "done",
    ]


@pytest.mark.asyncio
async def test_event_sequence_3_debaters_3_rounds():
    """3人×3ラウンドで要約が2回入る。"""
    manager = make_manager(num_debaters=3, num_rounds=3)
    events = await collect_events(manager)

    types = [e["type"] for e in events]
    # 要約はラウンド1,2の後に入る（ラウンド3の後は結論）
    summary_count = sum(
        1 for e in events
        if e["type"] == "message" and e.get("speaker") == "facilitator" and e.get("round", 0) > 0
    )
    assert summary_count == 2

    assert types[0] == "message"   # opening
    assert types[-1] == "done"
    assert types[-2] == "conclusion"


@pytest.mark.asyncio
async def test_facilitator_opening_is_first():
    """最初のイベントはファシリテーターの開会メッセージ。"""
    manager = make_manager()
    events = await collect_events(manager)

    opening = events[0]
    assert opening["type"] == "message"
    assert opening["speaker"] == "facilitator"
    assert opening["round"] == 0


@pytest.mark.asyncio
async def test_conclusion_is_last_message():
    """done直前にconclusionがある。"""
    manager = make_manager()
    events = await collect_events(manager)

    assert events[-1]["type"] == "done"
    assert events[-2]["type"] == "conclusion"
    assert events[-2]["speaker"] == "facilitator"


@pytest.mark.asyncio
async def test_debater_messages_have_correct_round():
    """各討論者のメッセージに正しいラウンド番号が付く。"""
    manager = make_manager(num_debaters=2, num_rounds=2)
    events = await collect_events(manager)

    debater_msgs = [
        e for e in events
        if e["type"] == "message" and e.get("speaker") not in ("facilitator",)
    ]
    rounds = [m["round"] for m in debater_msgs]
    assert rounds == [1, 1, 2, 2]


@pytest.mark.asyncio
async def test_all_debaters_are_called_each_round():
    """全討論者が毎ラウンド1回ずつ呼ばれる。"""
    alice = MockLLMClient("Alice")
    bob = MockLLMClient("Bob")
    manager = make_manager(
        debaters={"a": alice, "b": bob},
        num_rounds=3,
    )
    await collect_events(manager)

    assert len(alice.calls) == 3
    assert len(bob.calls) == 3


@pytest.mark.asyncio
async def test_facilitator_call_count():
    """ファシリテーターの呼び出し回数: 開会1 + 要約(rounds-1) + 結論1。"""
    facilitator = MockLLMClient("Facilitator")
    manager = make_manager(num_rounds=3, facilitator=facilitator)
    await collect_events(manager)

    # 開会(1) + 要約(2) + 結論(1) = 4
    assert len(facilitator.calls) == 4


@pytest.mark.asyncio
async def test_history_grows_across_rounds():
    """ラウンドが進むにつれて討論者に渡される履歴が長くなる。"""
    alice = MockLLMClient("Alice", response="Aliceの意見")
    bob = MockLLMClient("Bob", response="Bobの意見")
    manager = make_manager(
        debaters={"a": alice, "b": bob},
        num_rounds=2,
    )
    await collect_events(manager)

    # ラウンド1のプロンプトには「まだ発言はありません」ではなく開会メッセージが含まれる
    round1_prompt = alice.calls[0][1]  # user_prompt
    round2_prompt = alice.calls[1][1]

    assert len(round2_prompt) > len(round1_prompt)
    # ラウンド2のプロンプトにはラウンド1の発言が含まれる
    assert "Aliceの意見" in round2_prompt
    assert "Bobの意見" in round2_prompt


@pytest.mark.asyncio
async def test_debater_error_is_caught():
    """討論者のAPI呼び出しが失敗してもエラーメッセージとして議論が続行する。"""
    failing = FailingLLMClient("FailBot", fail_times=999)
    normal = MockLLMClient("Normal")
    manager = make_manager(
        debaters={"f": failing, "n": normal},
        num_rounds=1,
    )
    events = await collect_events(manager)

    debater_msgs = [
        e for e in events
        if e["type"] == "message" and e.get("speaker") not in ("facilitator",)
    ]
    contents = {m["display_name"]: m["content"] for m in debater_msgs}

    assert "応答エラー" in contents["FailBot"]
    assert contents["Normal"] == "Normalの回答です。"
    # 結論まで到達している
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_facilitator_error_is_caught():
    """ファシリテーターの要約が失敗しても議論は続行する。"""
    facilitator = FailingLLMClient("Facilitator", fail_times=1)
    manager = make_manager(num_rounds=2, facilitator=facilitator)
    events = await collect_events(manager)

    # 開会で失敗するが、要約・結論へ進む
    # エラーが含まれるが done まで到達する
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_messages_stored_in_manager():
    """議論中のメッセージがmanager.messagesに蓄積される。"""
    manager = make_manager(num_debaters=2, num_rounds=1)
    await collect_events(manager)

    # opening(1) + debater×2 = 3 (round_start, conclusion, done は含まない)
    assert len(manager.messages) == 3


@pytest.mark.asyncio
async def test_debaters_called_in_parallel():
    """同一ラウンド内の討論者が並列に呼ばれていることを確認する。"""
    call_order = []

    class SlowClient(MockLLMClient):
        async def generate(self, system_prompt, user_prompt, **kwargs):
            call_order.append(f"{self.display_name}_start")
            await asyncio.sleep(0.05)
            call_order.append(f"{self.display_name}_end")
            return f"{self.display_name}の回答"

    alice = SlowClient("Alice")
    bob = SlowClient("Bob")
    manager = make_manager(
        debaters={"a": alice, "b": bob},
        num_rounds=1,
    )
    await collect_events(manager)

    # 並列なら両方startしてから両方endする
    starts = [i for i, x in enumerate(call_order) if x.endswith("_start")]
    ends = [i for i, x in enumerate(call_order) if x.endswith("_end")]
    # 両方のstartが両方のendより前にある
    assert max(starts) < min(ends)


@pytest.mark.asyncio
async def test_format_history_empty():
    """メッセージがない状態の履歴フォーマット。"""
    manager = make_manager()
    assert manager._format_history() == "(まだ発言はありません)"


@pytest.mark.asyncio
async def test_format_history_with_messages():
    """メッセージが蓄積された状態の履歴フォーマット。"""
    manager = make_manager()
    manager.messages.append(
        {"display_name": "Alice", "content": "テスト発言"}
    )
    history = manager._format_history()
    assert "【Alice】" in history
    assert "テスト発言" in history


@pytest.mark.asyncio
async def test_system_prompt_contains_debater_name():
    """討論者のシステムプロンプトに名前が含まれる。"""
    manager = make_manager()
    prompt = manager._debater_system_prompt("TestBot")
    assert "TestBot" in prompt


@pytest.mark.asyncio
async def test_opening_prompt_lists_all_debaters():
    """開会プロンプトに全参加者名が含まれる。"""
    alice = MockLLMClient("Alice")
    bob = MockLLMClient("Bob")
    manager = make_manager(debaters={"a": alice, "b": bob})
    prompt = manager._facilitator_opening_prompt()
    assert "Alice" in prompt
    assert "Bob" in prompt
