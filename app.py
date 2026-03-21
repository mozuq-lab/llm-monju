import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from debate import DebateManager
from llm_clients import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_MODELS = [
    {"model": "anthropic/claude-opus-4.6", "name": "Claude"},
    {"model": "openai/gpt-5.4", "name": "ChatGPT"},
    {"model": "google/gemini-3.1-pro-preview", "name": "Gemini"},
    {"model": "x-ai/grok-4.20-beta", "name": "Grok"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY が設定されていません")
    app.state.openrouter = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/monju",
            "X-Title": "Monju - Multi-AI Debate",
        },
    )
    yield


app = FastAPI(title="文殊 Monju", lifespan=lifespan)


class ModelConfig(BaseModel):
    model: str
    name: str


class DebateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    num_rounds: int = Field(3, ge=1, le=5)
    debaters: List[ModelConfig]
    facilitator: ModelConfig


@app.get("/api/defaults")
async def get_defaults():
    return {"models": DEFAULT_MODELS}


@app.post("/api/debate")
async def start_debate(request: DebateRequest):
    if len(request.debaters) < 2:
        return JSONResponse(
            status_code=400,
            content={"error": "議論には最低2つのモデルを選択してください。"},
        )

    client = app.state.openrouter

    debaters = {}
    for i, cfg in enumerate(request.debaters):
        debaters[f"debater_{i}"] = LLMClient(
            client=client, model=cfg.model, display_name=cfg.name
        )

    facilitator = LLMClient(
        client=client,
        model=request.facilitator.model,
        display_name="Facilitator",
    )

    manager = DebateManager(
        topic=request.topic,
        debaters=debaters,
        facilitator=facilitator,
        num_rounds=request.num_rounds,
    )

    async def event_stream():
        async for message in manager.run():
            yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(), media_type="text/event-stream; charset=utf-8"
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
