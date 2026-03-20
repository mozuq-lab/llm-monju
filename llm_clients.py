from __future__ import annotations

from openai import AsyncOpenAI


class LLMClient:
    """LLM client that calls models via OpenRouter."""

    def __init__(self, client: AsyncOpenAI, model: str, display_name: str):
        self.client = client
        self.model = model
        self.display_name = display_name
        self.name = display_name

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
