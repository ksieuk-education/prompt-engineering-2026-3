"""Локальная веб-монтажная. Запуск из корня: python -m studio."""

import asyncio
import json
import sys
from collections import OrderedDict
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field, ValidationError

from .agent import (
    ACTION_TOKENS,
    MODEL,
    OLLAMA,
    InvalidDecision,
    build_graph,
    call_instrument,
)
from .archive import CASES, ROOT, public_case
from .audio_search import Scope
from .recordings import FieldTarget
from .repeats import remember
from .transcript import passage_position, source_page


@asynccontextmanager
async def lifespan(app):
    process = StdioServerParameters(
        command=sys.executable, args=["-m", "studio.mcp_server"], cwd=ROOT
    )
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=4), trust_env=False
        ) as http,
        stdio_client(process) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        app.state.tools = [t.name for t in tools.tools]
        app.state.instruments = session
        app.state.graph = build_graph(http, session)
        app.state.http = http
        app.state.sessions = OrderedDict()
        yield


app = FastAPI(title="Вторая дорожка", lifespan=lifespan)


class NewSession(BaseModel):
    case_id: str


class Query(BaseModel):
    session: str
    question: str = Field(min_length=1, max_length=1400)


class SoundQuery(BaseModel):
    case_id: str
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    scope: Scope = "archive"


class RepeatQuery(SoundQuery):
    candidate_case: str = ""
    candidate_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    other_tape: bool = False


class FieldQuery(BaseModel):
    candidate: FieldTarget
    at: float = Field(ge=0, allow_inf_nan=False)
    scan_speed: bool = False


class TranscriptQuery(BaseModel):
    query: str = Field(min_length=1, max_length=180)
    page: int | None = Field(default=None, ge=1, le=624)
    exact: bool = False


@app.post("/api/field-transcript")
async def search_edition(body: TranscriptQuery, request: Request):
    return await call_instrument(
        request.app.state.instruments, "search_transcript", body.model_dump()
    )


@app.get("/api/field-transcript/pages/{number}")
async def edition_page(number: int, line_id: int | None = None):
    page = source_page(number)
    if page is None:
        raise HTTPException(404, "Страница отсутствует в этом издании.")
    if line_id is not None:
        focus = passage_position(number, line_id)
        if focus is None:
            raise HTTPException(404, "Указанная реплика не принадлежит этой странице.")
        return {**page, "focus": focus}
    return page


@app.post("/api/field-compare")
async def field_compare(body: FieldQuery, request: Request):
    result = await call_instrument(
        request.app.state.instruments, "compare_public", body.model_dump()
    )
    if result["status"] == "invalid_window":
        raise HTTPException(422, result["detail"])
    return result


@app.post("/api/sound-search")
async def sound_search(body: SoundQuery, request: Request):
    if body.case_id not in CASES:
        raise HTTPException(404, "Дело не найдено.")
    return await call_instrument(
        request.app.state.instruments, "match_sound", body.model_dump()
    )


@app.post("/api/repeat-clocks")
async def repeat_clocks(body: RepeatQuery, request: Request):
    if body.case_id not in CASES:
        raise HTTPException(404, "Дело не найдено.")
    return await call_instrument(
        request.app.state.instruments, "compare_repeat_clocks", body.model_dump()
    )


@app.get("/api/status")
async def status(request: Request):
    try:
        res = await request.app.state.http.get(OLLAMA + "/api/tags", timeout=2)
        res.raise_for_status()
        online = any(
            m["name"] == MODEL or m["name"] == MODEL + ":latest"
            for m in res.json().get("models", [])
        )
    except (httpx.HTTPError, ValueError):
        online = False
    return {
        "model": MODEL,
        "online": online,
        "mcp": request.app.state.tools,
        "action_tokens": ACTION_TOKENS,
    }


@app.get("/api/cases")
async def cases():
    return [public_case(key) for key in CASES]


@app.get("/api/examples/{case_id}")
async def example(case_id: str):
    if case_id not in CASES:
        raise HTTPException(404, "Дело не найдено.")
    file = ROOT / "examples" / (case_id + ".json")
    if not file.is_file():
        raise HTTPException(404, "Для этого дела еще нет сохраненного диалога.")
    return json.loads(file.read_text())


@app.post("/api/sessions")
async def new_session(body: NewSession, request: Request):
    if body.case_id not in CASES:
        raise HTTPException(404, "Дело не найдено.")
    sessions = request.app.state.sessions
    if len(sessions) >= 128:
        free = next(
            (key for key, v in sessions.items() if not v["lock"].locked()), None
        )
        if free is None:
            raise HTTPException(429, "Все сессии заняты.")
        del sessions[free]
    key = uuid4().hex
    sessions[key] = {"case": body.case_id, "lock": asyncio.Lock(), "history": []}
    return {"session": key}


@app.post("/api/ask")
async def ask(body: Query, request: Request):
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Введите вопрос.")
    sessions = request.app.state.sessions
    work = sessions.get(body.session)
    if work is None:
        raise HTTPException(404, "Сессия закончилась. Откройте дело заново.")
    sessions.move_to_end(body.session)
    async with work["lock"]:
        try:
            state = await request.app.state.graph.ainvoke(
                {"case": work["case"], "question": question, "history": work["history"]}
            )
        except InvalidDecision as err:
            raise HTTPException(502, str(err)) from err
        except (httpx.HTTPError, ValidationError, ValueError, RuntimeError) as err:
            raise HTTPException(
                503,
                "Не удалось получить ответ. Проверьте Ollama и наличие модели "
                + MODEL
                + ".",
            ) from err
        result = {
            **state["result"],
            "question": question,
            "steps": state["steps"],
            "model": MODEL,
        }
        if result["status"] in {"answered", "needs_input", "no_evidence"}:
            work["history"] = [
                *work["history"],
                {
                    "вопрос": question,
                    "ответ": result["answer"],
                    "источники": result["sources"],
                    **(
                        {"метка_копии": state["position_context"]}
                        if state.get("position_context")
                        else {}
                    ),
                    **(
                        {"звуковой_повтор": sound}
                        if (sound := remember(result["measurements"]))
                        else {}
                    ),
                    **(
                        {
                            "реплика_nasa": result["transcript"].get(
                                "reference_id",
                                next(
                                    (r["id"] for r in result["transcript"]["matches"]),
                                    result["transcript"]
                                    .get("counterexample", {})
                                    .get("id", 0),
                                ),
                            )
                        }
                        if "transcript" in result
                        else {}
                    ),
                    **(
                        {"открытая_сверка": state["public_audio"]}
                        if state.get("public_audio")
                        else {}
                    ),
                },
            ][-5:]
        return result


app.mount("/tapes", StaticFiles(directory=ROOT / "data/tapes"), name="tapes")
app.mount(
    "/field-audio", StaticFiles(directory=ROOT / "data/field"), name="field-audio"
)
app.mount("/", StaticFiles(directory=ROOT / "studio/web", html=True), name="studio")
