import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from debate import DebateManager
from llm_clients import get_available_clients

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    app.state.clients = get_available_clients()
    available = [c.display_name for c in app.state.clients.values()]
    logger.info("利用可能なモデル: %s", ", ".join(available) or "なし")
    yield


app = FastAPI(title="文殊 Monju", lifespan=lifespan)


class DebateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    num_rounds: int = Field(3, ge=1, le=5)
    models: Optional[List[str]] = None
    facilitator_model: Optional[str] = None


@app.get("/api/models")
async def get_models():
    clients = app.state.clients
    return {
        "available": [
            {"name": c.name, "display_name": c.display_name, "model": c.model}
            for c in clients.values()
        ]
    }


@app.post("/api/debate")
async def start_debate(request: DebateRequest):
    all_clients = app.state.clients

    if len(all_clients) < 2:
        return JSONResponse(
            status_code=400,
            content={"error": "議論には最低2つのモデルが必要です。APIキーを確認してください。"},
        )

    # Select debaters
    if request.models:
        debaters = {k: v for k, v in all_clients.items() if k in request.models}
    else:
        debaters = dict(all_clients)

    if len(debaters) < 2:
        return JSONResponse(
            status_code=400,
            content={"error": "議論には最低2つのモデルを選択してください。"},
        )

    # Select facilitator
    facilitator_key = request.facilitator_model
    if facilitator_key and facilitator_key in all_clients:
        facilitator = all_clients[facilitator_key]
    else:
        facilitator = next(iter(all_clients.values()))

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
