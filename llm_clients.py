from __future__ import annotations

import os

from openai import AsyncOpenAI

DEFAULT_MAX_TOKENS = int(os.environ.get("MONJU_MAX_TOKENS", "4096"))
DEFAULT_TIMEOUT = int(os.environ.get("MONJU_TIMEOUT", "120"))


class LLMClient:
    """LLM client that calls models via OpenRouter."""

    def __init__(self, client: AsyncOpenAI, model: str, display_name: str):
        self.client = client
        self.model = model
        self.display_name = display_name
        self.name = display_name

    async def generate(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 0
    ) -> str:
        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            timeout=DEFAULT_TIMEOUT,
        )
        return response.choices[0].message.content or ""
