import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from db import init_db, save_debate, list_debates, get_debate, export_debate_markdown
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
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monju.db")
    app.state.db = await init_db(db_path)
    yield
    await app.state.db.close()


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
        debate_id = uuid.uuid4().hex
        events = []
        async for message in manager.run():
            events.append(message)
            if message.get("type") == "done":
                message["debate_id"] = debate_id
            yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
        # Save after stream completes (client already received all data)
        try:
            await save_debate(
                db=app.state.db,
                debate_id=debate_id,
                topic=request.topic,
                num_rounds=request.num_rounds,
                debater_models=[d.dict() for d in request.debaters],
                facilitator_model=request.facilitator.dict(),
                events=events,
            )
        except Exception:
            logger.exception("議論の保存に失敗しました")

    return StreamingResponse(
        event_stream(), media_type="text/event-stream; charset=utf-8"
    )


@app.get("/api/debates")
async def get_debates():
    debates = await list_debates(app.state.db)
    return {"debates": debates}


@app.get("/api/debates/{debate_id}")
async def get_debate_by_id(debate_id: str):
    debate = await get_debate(app.state.db, debate_id)
    if debate is None:
        return JSONResponse(status_code=404, content={"error": "議論が見つかりません"})
    return debate


@app.get("/api/debates/{debate_id}/export")
async def export_debate(debate_id: str):
    md = await export_debate_markdown(app.state.db, debate_id)
    if md is None:
        return JSONResponse(status_code=404, content={"error": "議論が見つかりません"})
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="monju-{debate_id[:8]}.md"'
        },
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
