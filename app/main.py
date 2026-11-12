from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .agent import Agent
from .db import Database
from .knowledge import FAQ
from .llm import build_llm
from .ratelimit import DailyBudget, RateLimiter

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class ChatIn(BaseModel):
    session_id: str = Field(pattern=SESSION_PATTERN)
    message: str = Field(min_length=1, max_length=2000)


class ChatOut(BaseModel):
    reply: str
    handoff: bool
    tools_used: list[str]


class TeachIn(BaseModel):
    resposta: str = Field(min_length=3, max_length=800)
    pergunta: str | None = Field(default=None, max_length=300)


def build_agent() -> Agent:
    return Agent(db=Database(config.DB_PATH), faq=FAQ(config.FAQ_PATH), llm=build_llm())


def create_app(agent: Agent | None = None, limiter: RateLimiter | None = None,
               panel_token: str | None = None, budget: DailyBudget | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if agent is None:
        if not config.LLM_API_KEY:
            logging.getLogger("agente").warning("LLM_API_KEY vazia: configure o .env (veja .env.example)")
        agent = build_agent()
    db = agent.db
    limiter = limiter or RateLimiter(max_calls=config.RATE_LIMIT_PER_MINUTE, window=60)
    budget = budget or DailyBudget(config.DAILY_MESSAGE_LIMIT)
    token = config.PANEL_TOKEN if panel_token is None else panel_token

    app = FastAPI(title="Agente de atendimento para marcenaria", docs_url="/api/docs", redoc_url=None)

    def client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "desconhecido"

    def require_panel(query_token: str | None, header_token: str | None) -> None:
        if not token:
            return
        given = header_token or query_token or ""
        if not hmac.compare_digest(given, token):
            raise HTTPException(status_code=401, detail="Token do painel inválido.")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/info")
    def info():
        return {
            "business": agent.business_name,
            "greeting": agent.greeting,
            "video_url": config.DEMO_VIDEO_URL,
            "repo_url": config.REPO_URL,
        }

    @app.post("/api/chat", response_model=ChatOut)
    def chat(body: ChatIn, request: Request):
        if not limiter.allow(client_ip(request)):
            raise HTTPException(status_code=429, detail="Muitas mensagens em pouco tempo. Aguarde um instante.")
        if not budget.take():
            raise HTTPException(status_code=503, detail={
                "code": "demo_limit",
                "message": "A demonstração atingiu o limite de uso de hoje.",
            })
        result = agent.reply(body.session_id, body.message)
        return ChatOut(reply=result.reply, handoff=result.handoff, tools_used=result.tools_used)

    @app.get("/api/sessions/{session_id}")
    def session_history(session_id: str):
        session = db.get_session(session_id)
        visible = [
            {"role": m["role"], "content": m["content"]}
            for m in session["messages"]
            if m["role"] in ("user", "assistant") and m.get("content")
        ]
        return {
            "messages": visible,
            "handoff": bool(session["handoff_reason"]),
            "lead": db.get_lead(session_id),
            "visit": db.get_visit(session_id),
        }

    @app.get("/api/leads")
    def leads(token: str | None = None, x_panel_token: str | None = Header(default=None)):
        require_panel(token, x_panel_token)
        return {"leads": db.list_leads()}

    @app.get("/api/leads/{session_id}/transcript")
    def transcript(session_id: str, token: str | None = None, x_panel_token: str | None = Header(default=None)):
        require_panel(token, x_panel_token)
        return session_history(session_id)

    @app.get("/api/gaps")
    def gaps(token: str | None = None, x_panel_token: str | None = Header(default=None)):
        require_panel(token, x_panel_token)
        return {"gaps": db.list_gaps(), "learned": db.list_learned()}

    @app.post("/api/gaps/{gap_id}/answer")
    def answer_gap(gap_id: int, body: TeachIn, token: str | None = None,
                   x_panel_token: str | None = Header(default=None)):
        require_panel(token, x_panel_token)
        gap = db.get_gap(gap_id)
        if gap is None:
            raise HTTPException(status_code=404, detail="Dúvida não encontrada.")
        resposta = body.resposta.strip()
        if len(resposta) < 3:
            raise HTTPException(status_code=422, detail="Resposta muito curta.")
        db.teach((body.pergunta or gap["question"]).strip(), resposta, gap_id)
        return {"ok": True}

    @app.post("/api/gaps/{gap_id}/dismiss")
    def dismiss_gap(gap_id: int, token: str | None = None, x_panel_token: str | None = Header(default=None)):
        require_panel(token, x_panel_token)
        db.dismiss_gap(gap_id)
        return {"ok": True}

    @app.delete("/api/learned/{learned_id}")
    def delete_learned(learned_id: int, token: str | None = None, x_panel_token: str | None = Header(default=None)):
        require_panel(token, x_panel_token)
        db.delete_learned(learned_id)
        return {"ok": True}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
