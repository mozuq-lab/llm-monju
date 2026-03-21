from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from llm_clients import LLMClient


class DebateManager:
    def __init__(
        self,
        topic: str,
        debaters: dict[str, LLMClient],
        facilitator: LLMClient,
        num_rounds: int = 3,
    ):
        self.topic = topic
        self.debaters = debaters
        self.facilitator = facilitator
        self.num_rounds = num_rounds
        self.messages: list[dict] = []

    def _format_history(self) -> str:
        if not self.messages:
            return "(まだ発言はありません)"
        lines = []
        for msg in self.messages:
            lines.append(f"【{msg['display_name']}】\n{msg['content']}")
        return "\n\n".join(lines)

    def _debater_system_prompt(self, name: str) -> str:
        return (
            f"あなたは{name}です。複数のAIモデルによる議論に参加しています。\n"
            f"お題について自分の分析や見解を率直に述べてください。\n"
            f"他の参加者の意見に対して、同意・反論・補足を積極的に行ってください。\n"
            f"簡潔かつ的確に、400字程度で議論してください。\n"
            f"日本語で回答してください。"
        )

    def _debater_user_prompt(self, round_num: int) -> str:
        history = self._format_history()
        return (
            f"議論のお題: {self.topic}\n\n"
            f"これまでの議論:\n{history}\n\n"
            f"---\n"
            f"ラウンド{round_num}のあなたの見解を述べてください。"
        )

    def _facilitator_system_prompt(self) -> str:
        return (
            "あなたは議論のファシリテーターです。\n"
            "複数のAIモデルが一つのお題について議論しています。\n"
            "中立的な立場を保ち、建設的な議論を導いてください。\n"
            "日本語で回答してください。"
        )

    def _facilitator_opening_prompt(self) -> str:
        debater_names = "、".join(d.display_name for d in self.debaters.values())
        return (
            f"議論のお題: {self.topic}\n\n"
            f"参加者: {debater_names}\n\n"
            f"議論の開始を宣言し、お題の背景や論点を簡潔に紹介してください。\n"
            f"200字程度でお願いします。"
        )

    def _facilitator_summary_prompt(self, round_num: int) -> str:
        history = self._format_history()
        return (
            f"議論のお題: {self.topic}\n\n"
            f"これまでの議論:\n{history}\n\n"
            f"---\n"
            f"ラウンド{round_num}の議論を要約し、論点を整理してください。\n"
            f"次のラウンドに向けて、深掘りすべきポイントを提示してください。\n"
            f"250字程度でお願いします。"
        )

    def _facilitator_conclusion_prompt(self) -> str:
        history = self._format_history()
        debater_names = "、".join(d.display_name for d in self.debaters.values())
        return (
            f"議論のお題: {self.topic}\n\n"
            f"参加者: {debater_names}\n\n"
            f"全議論の記録:\n{history}\n\n"
            f"---\n"
            f"全ラウンドの議論を踏まえ、最終的な結論をまとめてください。\n"
            f"以下の構成で記述してください:\n"
            f"1. 各参加者の主要な主張の整理\n"
            f"2. 合意点\n"
            f"3. 相違点\n"
            f"4. 総合的な結論\n"
        )

    async def _get_response(
        self, client: LLMClient, user_prompt: str
    ) -> tuple[LLMClient, str]:
        try:
            content = await client.generate(
                self._debater_system_prompt(client.display_name),
                user_prompt,
            )
            return client, content
        except Exception as e:
            return client, f"[応答エラー: {type(e).__name__}: {e}]"

    async def run(self) -> AsyncGenerator[dict, None]:
        """Run the debate, yielding messages as they're generated."""

        # Facilitator opening
        try:
            opening = await self.facilitator.generate(
                self._facilitator_system_prompt(),
                self._facilitator_opening_prompt(),
            )
        except Exception as e:
            opening = f"[ファシリテーター応答エラー: {e}]"
        msg = {
            "type": "message",
            "speaker": "facilitator",
            "display_name": "Facilitator",
            "content": opening,
            "round": 0,
        }
        self.messages.append(msg)
        yield msg

        # Debate rounds
        for round_num in range(1, self.num_rounds + 1):
            yield {"type": "round_start", "round": round_num}

            # All debaters respond in parallel
            user_prompt = self._debater_user_prompt(round_num)
            tasks = [
                self._get_response(client, user_prompt)
                for client in self.debaters.values()
            ]
            results = await asyncio.gather(*tasks)

            for client, content in results:
                msg = {
                    "type": "message",
                    "speaker": client.name,
                    "display_name": client.display_name,
                    "content": content,
                    "round": round_num,
                }
                self.messages.append(msg)
                yield msg

            # Facilitator summary between rounds
            if round_num < self.num_rounds:
                try:
                    summary = await self.facilitator.generate(
                        self._facilitator_system_prompt(),
                        self._facilitator_summary_prompt(round_num),
                    )
                except Exception as e:
                    summary = f"[ファシリテーター応答エラー: {e}]"

                msg = {
                    "type": "message",
                    "speaker": "facilitator",
                    "display_name": "Facilitator",
                    "content": summary,
                    "round": round_num,
                }
                self.messages.append(msg)
                yield msg

        # Final conclusion
        yield {"type": "generating_conclusion"}
        try:
            conclusion = await self.facilitator.generate(
                self._facilitator_system_prompt(),
                self._facilitator_conclusion_prompt(),
            )
        except Exception as e:
            conclusion = f"[結論生成エラー: {e}]"

        yield {
            "type": "conclusion",
            "speaker": "facilitator",
            "display_name": "Facilitator",
            "content": conclusion,
        }

        yield {"type": "done"}
