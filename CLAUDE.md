# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

文殊 (Monju) is a multi-LLM debate system. Given a topic, multiple AI models debate it over multiple rounds, with a separate facilitator AI that summarizes each round and produces a structured final conclusion. All model calls go through OpenRouter (OpenAI-compatible API), so a single API key accesses any model.

## Commands

```bash
# Setup virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the server (serves Web UI at http://localhost:8000)
python app.py

# API key is loaded from .env (copy .env.example to .env)
# Only OPENROUTER_API_KEY is needed
```

```bash
# Run tests (no API key required — uses mock clients and in-memory SQLite)
pytest test_debate.py test_db.py -v
```

## Architecture

The app is a FastAPI server with a vanilla HTML/JS frontend, connected via Server-Sent Events (SSE).

**Debate flow:** User submits topic + model configs via POST `/api/debate` → `DebateManager.run()` is an async generator that yields SSE events → FastAPI streams them to the browser.

**Key design decisions:**
- All LLM calls go through a single `LLMClient` class that wraps `openai.AsyncOpenAI` pointed at OpenRouter's base URL. No provider-specific SDKs.
- Debater model IDs and display names are sent from the frontend per-request, not fixed at startup.
- Each round, all debaters are called **in parallel** via `asyncio.gather()`, then the facilitator is called sequentially to summarize.
- Each debater receives the **full conversation history** as a formatted string in its user prompt (not as multi-turn chat). This keeps the interface uniform across models.
- The facilitator uses the same `LLMClient` class as debaters but with different system/user prompts.
- A single shared `AsyncOpenAI` instance (created at startup in `app.state.openrouter`) is reused across all `LLMClient` instances.

**Persistence:** Completed debates are saved to SQLite (`monju.db`, auto-created) via `db.py`. Saving happens after the SSE stream completes, so it never delays delivery. The `done` SSE event includes `debate_id` so the frontend can immediately construct share URLs. Past debates are viewable via `/?id={debate_id}` and exportable as Markdown via `GET /api/debates/{id}/export`.

**Intervention mode:** When `intervention: true` is sent in the debate request, the debate runs round-by-round instead of as a single stream. `POST /api/debate` runs the opening + Round 1, then pauses with an `awaiting_input` event. `POST /api/debate/{id}/next` advances one round, optionally accepting user feedback via `inject_human_message()` that becomes part of the conversation context. `POST /api/debate/{id}/conclude` skips remaining rounds and generates the conclusion. Active debate state is held in memory (`app.state.active_debates`) with a 1-hour TTL. When `intervention: false` (default), the existing single-stream `run()` is used.

## Conventions

- Python 3.9 compatibility is required. Use `from __future__ import annotations` for modern type hint syntax. Use `typing.Optional`/`typing.List` in Pydantic models (Pydantic evaluates annotations at runtime, bypassing `__future__`).
- All user-facing text (prompts, UI, error messages) is in Japanese.
- The frontend is a single `static/index.html` with no build tools or frameworks.
