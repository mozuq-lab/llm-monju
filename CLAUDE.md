# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

文殊 (Monju) is a multi-LLM debate system. Given a topic, multiple AI models (Claude, ChatGPT, Gemini, Grok) debate it over multiple rounds, with a separate facilitator AI that summarizes each round and produces a structured final conclusion.

## Commands

```bash
# Setup virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the server (serves Web UI at http://localhost:8000)
python app.py

# API keys are loaded from .env (copy .env.example to .env)
```

There are no tests, linters, or build steps configured.

## Architecture

The app is a FastAPI server with a vanilla HTML/JS frontend, connected via Server-Sent Events (SSE).

**Debate flow:** User submits topic via POST `/api/debate` → `DebateManager.run()` is an async generator that yields SSE events → FastAPI streams them to the browser.

**Key design decisions:**
- Each round, all debaters are called **in parallel** via `asyncio.gather()`, then the facilitator is called sequentially to summarize.
- Each debater receives the **full conversation history** as a formatted string in its user prompt (not as multi-turn chat). This keeps the API interface uniform across providers.
- The facilitator uses the same LLM client as a debater but with different system/user prompts. The same model instance can serve both roles.
- `get_available_clients()` in `llm_clients.py` auto-detects which models are available based on which env vars are set. Minimum 2 models required.

**LLM client abstraction:** `LLMClient` is an ABC with a single `async generate(system_prompt, user_prompt) -> str` method. Each provider subclass wraps its own SDK (anthropic, openai, google-genai). Grok uses the OpenAI SDK with a custom base URL.

## Conventions

- Python 3.9 compatibility is required. Use `from __future__ import annotations` for modern type hint syntax. Use `typing.Optional`/`typing.List` in Pydantic models (Pydantic evaluates annotations at runtime, bypassing `__future__`).
- All user-facing text (prompts, UI, error messages) is in Japanese.
- The frontend is a single `static/index.html` with no build tools or frameworks.
