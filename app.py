import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

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

ACTIVE_DEBATE_TTL = 3600  # 1 hour


@dataclass
class ActiveDebate:
    manager: DebateManager
    debate_id: str
    topic: str
    num_rounds: int
    current_round: int
    debater_models: list
    facilitator_model: dict
    events: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    in_progress: bool = False


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
    app.state.active_debates = {}
    yield
    await app.state.db.close()


app = FastAPI(title="文殊 Monju", lifespan=lifespan)


# --- Request models ---


class ModelConfig(BaseModel):
    model: str
    name: str


class DebateRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    num_rounds: int = Field(3, ge=1, le=5)
    debaters: List[ModelConfig]
    facilitator: ModelConfig
    intervention: bool = False

    @field_validator("topic")
    @classmethod
    def check_topic_length(cls, v):
        limit = int(os.environ.get("MONJU_MAX_TOPIC_LENGTH", "5000"))
        if len(v) > limit:
            raise ValueError(f"お題は{limit}文字以内にしてください")
        return v


class NextRoundRequest(BaseModel):
    input: Optional[str] = None


# --- Helpers ---


def _create_manager(request: DebateRequest, client) -> DebateManager:
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
    return DebateManager(
        topic=request.topic,
        debaters=debaters,
        facilitator=facilitator,
        num_rounds=request.num_rounds,
    )


def _cleanup_stale(active_debates: dict) -> None:
    now = time.time()
    stale = [k for k, v in active_debates.items() if now - v.created_at > ACTIVE_DEBATE_TTL]
    for k in stale:
        del active_debates[k]


async def _save_completed(active: ActiveDebate) -> None:
    try:
        await save_debate(
            db=app.state.db,
            debate_id=active.debate_id,
            topic=active.topic,
            num_rounds=active.num_rounds,
            debater_models=active.debater_models,
            facilitator_model=active.facilitator_model,
            events=active.events,
        )
    except Exception:
        logger.exception("議論の保存に失敗しました")


def _get_active(debate_id: str):
    _cleanup_stale(app.state.active_debates)
    active = app.state.active_debates.get(debate_id)
    if active is None:
        return None, JSONResponse(status_code=404, content={"error": "議論が見つかりません"})
    if active.in_progress:
        return None, JSONResponse(status_code=409, content={"error": "前のラウンドがまだ実行中です"})
    return active, None


# --- Endpoints ---


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
    manager = _create_manager(request, client)

    if not request.intervention:
        # Auto mode: run full debate as single SSE stream
        async def auto_stream():
            debate_id = uuid.uuid4().hex
            events = []
            async for message in manager.run():
                events.append(message)
                if message.get("type") == "done":
                    message["debate_id"] = debate_id
                yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
            try:
                await save_debate(
                    db=app.state.db,
                    debate_id=debate_id,
                    topic=request.topic,
                    num_rounds=request.num_rounds,
                    debater_models=[d.model_dump() for d in request.debaters],
                    facilitator_model=request.facilitator.model_dump(),
                    events=events,
                )
            except Exception:
                logger.exception("議論の保存に失敗しました")

        return StreamingResponse(
            auto_stream(), media_type="text/event-stream; charset=utf-8"
        )

    # Intervention mode: run opening + round 1, then pause
    debate_id = uuid.uuid4().hex
    active = ActiveDebate(
        manager=manager,
        debate_id=debate_id,
        topic=request.topic,
        num_rounds=request.num_rounds,
        current_round=2,  # next round to run
        debater_models=[d.model_dump() for d in request.debaters],
        facilitator_model=request.facilitator.model_dump(),
    )
    app.state.active_debates[debate_id] = active

    async def intervention_stream():
        active.in_progress = True
        try:
            yield f"data: {json.dumps({'type': 'debate_started', 'debate_id': debate_id}, ensure_ascii=False)}\n\n"

            async for event in manager.run_opening():
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            is_only_round = request.num_rounds == 1
            async for event in manager.run_round(1):
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if is_only_round:
                async for event in manager.run_conclude():
                    active.events.append(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                async for event in manager.run_issue_map():
                    active.events.append(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                await _save_completed(active)
                cont = {"type": "awaiting_continuation"}
                active.events.append(cont)
                yield f"data: {json.dumps(cont, ensure_ascii=False)}\n\n"
            else:
                awaiting = {
                    "type": "awaiting_input",
                    "round_completed": 1,
                    "rounds_remaining": request.num_rounds - 1,
                }
                active.events.append(awaiting)
                yield f"data: {json.dumps(awaiting, ensure_ascii=False)}\n\n"
        finally:
            active.in_progress = False

    return StreamingResponse(
        intervention_stream(), media_type="text/event-stream; charset=utf-8"
    )


@app.post("/api/debate/{debate_id}/next")
async def next_round(debate_id: str, request: NextRoundRequest = None):
    active, error = _get_active(debate_id)
    if error:
        return error

    manager = active.manager
    round_num = active.current_round

    async def round_stream():
        active.in_progress = True
        try:
            # Inject human message if provided
            if request and request.input:
                msg = manager.inject_human_message(request.input, after_round=round_num - 1)
                active.events.append(msg)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

            async for event in manager.run_round(round_num):
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            is_last = round_num >= active.num_rounds
            if is_last:
                async for event in manager.run_conclude():
                    active.events.append(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                async for event in manager.run_issue_map():
                    active.events.append(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                await _save_completed(active)
                cont = {"type": "awaiting_continuation"}
                active.events.append(cont)
                yield f"data: {json.dumps(cont, ensure_ascii=False)}\n\n"
            else:
                active.current_round = round_num + 1
                awaiting = {
                    "type": "awaiting_input",
                    "round_completed": round_num,
                    "rounds_remaining": active.num_rounds - round_num,
                }
                active.events.append(awaiting)
                yield f"data: {json.dumps(awaiting, ensure_ascii=False)}\n\n"
        finally:
            active.in_progress = False

    return StreamingResponse(
        round_stream(), media_type="text/event-stream; charset=utf-8"
    )


@app.post("/api/debate/{debate_id}/conclude")
async def conclude_debate(debate_id: str, request: NextRoundRequest = None):
    active, error = _get_active(debate_id)
    if error:
        return error

    manager = active.manager

    async def conclude_stream():
        active.in_progress = True
        try:
            if request and request.input:
                msg = manager.inject_human_message(
                    request.input, after_round=active.current_round - 1
                )
                active.events.append(msg)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

            async for event in manager.run_conclude():
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            async for event in manager.run_issue_map():
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            await _save_completed(active)
            cont = {"type": "awaiting_continuation"}
            active.events.append(cont)
            yield f"data: {json.dumps(cont, ensure_ascii=False)}\n\n"
        finally:
            active.in_progress = False

    return StreamingResponse(
        conclude_stream(), media_type="text/event-stream; charset=utf-8"
    )


@app.post("/api/debate/{debate_id}/extend")
async def extend_debate(debate_id: str, request: NextRoundRequest = None):
    active, error = _get_active(debate_id)
    if error:
        return error

    manager = active.manager
    active.num_rounds += 1
    round_num = active.num_rounds

    async def extend_stream():
        active.in_progress = True
        try:
            if request and request.input:
                msg = manager.inject_human_message(
                    request.input, after_round=round_num - 1
                )
                active.events.append(msg)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

            # Run one additional round (with facilitator summary)
            async for event in manager._run_single_round(round_num, is_last=False):
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # Generate new conclusion + issue map
            async for event in manager.run_conclude():
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            async for event in manager.run_issue_map():
                active.events.append(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            await _save_completed(active)
            cont = {"type": "awaiting_continuation"}
            active.events.append(cont)
            yield f"data: {json.dumps(cont, ensure_ascii=False)}\n\n"
        finally:
            active.in_progress = False

    return StreamingResponse(
        extend_stream(), media_type="text/event-stream; charset=utf-8"
    )


@app.post("/api/debate/{debate_id}/finish")
async def finish_debate(debate_id: str):
    active, error = _get_active(debate_id)
    if error:
        return error

    async def finish_stream():
        active.in_progress = True
        try:
            done = {"type": "done", "debate_id": debate_id}
            active.events.append(done)
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"

            await _save_completed(active)
            app.state.active_debates.pop(debate_id, None)
        finally:
            active.in_progress = False

    return StreamingResponse(
        finish_stream(), media_type="text/event-stream; charset=utf-8"
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
