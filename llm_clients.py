from __future__ import annotations

import os
from abc import ABC, abstractmethod

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from google import genai


class LLMClient(ABC):
    """Base class for LLM API clients."""

    def __init__(self, name: str, display_name: str, model: str):
        self.name = name
        self.display_name = display_name
        self.model = model

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class ClaudeClient(LLMClient):
    def __init__(self, model: str = "claude-sonnet-4-6"):
        super().__init__("claude", "Claude", model)
        self.client = AsyncAnthropic()

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text


class ChatGPTClient(LLMClient):
    def __init__(self, model: str = "gpt-4o"):
        super().__init__("chatgpt", "ChatGPT", model)
        self.client = AsyncOpenAI()

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


class GeminiClient(LLMClient):
    def __init__(self, model: str = "gemini-2.0-flash"):
        super().__init__("gemini", "Gemini", model)
        self.client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=2048,
            ),
        )
        return response.text


class GrokClient(LLMClient):
    def __init__(self, model: str = "grok-2"):
        super().__init__("grok", "Grok", model)
        self.client = AsyncOpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )

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


def get_available_clients() -> dict[str, LLMClient]:
    """Create clients for all models with available API keys."""
    clients = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        clients["claude"] = ClaudeClient()
    if os.environ.get("OPENAI_API_KEY"):
        clients["chatgpt"] = ChatGPTClient()
    if os.environ.get("GOOGLE_API_KEY"):
        clients["gemini"] = GeminiClient()
    if os.environ.get("XAI_API_KEY"):
        clients["grok"] = GrokClient()
    return clients
