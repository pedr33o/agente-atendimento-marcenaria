from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from . import config
from .db import Database
from .guardrails import check_reply
from .knowledge import FAQ
from .llm import LLMError
from .prompts import build_system_prompt
from .tools import TOOL_SCHEMAS, ToolRunner

log = logging.getLogger("agente")

MSG_HANDOFF_WAIT = "Já avisei um atendente da equipe. Ele continua a conversa por aqui assim que possível."
MSG_LIMIT = "Chegamos ao limite de mensagens desta conversa de demonstração. Um atendente pode continuar com você."
MSG_ERROR = "Tive uma instabilidade aqui. Pode mandar sua mensagem de novo em instantes?"
MSG_EMPTY = "Não consegui entender direito. Pode me explicar de outro jeito?"
MSG_STEPS = "Isso está pedindo uma análise mais cuidadosa, então vou chamar um atendente para continuar com você."


@dataclass
class AgentResult:
    reply: str
    handoff: bool = False
    tools_used: list[str] = field(default_factory=list)
    error: bool = False
    blocked: str | None = None


class Agent:
    def __init__(self, db: Database, faq: FAQ, llm, now=datetime.now,
                 max_user_messages: int = config.MAX_USER_MESSAGES,
                 max_input_chars: int = config.MAX_INPUT_CHARS,
                 max_tool_steps: int = config.MAX_TOOL_STEPS,
                 business_name: str = config.BUSINESS_NAME,
                 greeting: str = config.GREETING):
        self.db, self.faq, self.llm, self.now = db, faq, llm, now
        self.max_user_messages = max_user_messages
        self.max_input_chars = max_input_chars
        self.max_tool_steps = max_tool_steps
        self.business_name = business_name
        self.greeting = greeting

    def reply(self, session_id: str, user_text: str) -> AgentResult:
        text = (user_text or "").strip()
        if not text:
            raise ValueError("mensagem vazia")
        text = text[: self.max_input_chars]

        session = self.db.get_session(session_id)
        count = session["user_msg_count"]
        already_handoff = bool(session["handoff_reason"])

        if count >= self.max_user_messages:
            return AgentResult(MSG_LIMIT, handoff=already_handoff, blocked="limit")

        messages = session["messages"] + [{"role": "user", "content": text}]
        count += 1

        if already_handoff:
            messages.append({"role": "assistant", "content": MSG_HANDOFF_WAIT})
            self.db.save_session(session_id, messages, count)
            return AgentResult(MSG_HANDOFF_WAIT, handoff=True, blocked="handoff")

        tools = ToolRunner(self.db, self.faq, session_id, self.now)
        knowledge = self.faq.search(text, extra=self.db.list_learned())
        system = {"role": "system", "content": build_system_prompt(
            self.now(), self.business_name, self.greeting, knowledge)}
        used: list[str] = []
        final: str | None = None

        try:
            for _ in range(self.max_tool_steps):
                msg = self._normalize(self.llm.chat([system] + messages, TOOL_SCHEMAS))
                messages.append(msg)
                calls = msg.get("tool_calls")
                if not calls:
                    final = msg["content"]
                    break
                for call in calls:
                    name = call["function"]["name"]
                    args = self._parse_args(call["function"]["arguments"])
                    result = tools.run(name, args)
                    used.append(name)
                    log.info("tool=%s args=%s ok=%s", name, json.dumps(args, ensure_ascii=False), "erro" not in result)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
        except LLMError as exc:
            log.error("falha do modelo: %s", exc)
            return AgentResult(MSG_ERROR, error=True, tools_used=used)

        if final is None:
            tools.run("transferir_para_humano", {"motivo": "agente excedeu o limite de passos"})
            final = MSG_STEPS
            messages.append({"role": "assistant", "content": final})
        elif not final.strip():
            final = MSG_EMPTY
            messages[-1]["content"] = final

        final, violations = check_reply(final)
        if violations:
            log.warning("guardrail acionado: %s", violations)
            messages[-1]["content"] = final

        self.db.save_session(session_id, messages, count)
        handoff = bool(self.db.get_session(session_id)["handoff_reason"])
        return AgentResult(final, handoff=handoff, tools_used=used,
                           blocked=violations[0] if violations else None)

    @staticmethod
    def _normalize(msg: dict) -> dict:
        out: dict = {"role": "assistant", "content": msg.get("content") or ""}
        calls = []
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments")
            entry = {
                "id": call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": args if isinstance(args, str) else json.dumps(args or {}),
                },
            }
            if isinstance(call.get("extra_content"), dict):
                entry["extra_content"] = call["extra_content"]
            calls.append(entry)
        if calls:
            out["tool_calls"] = calls
        return out

    @staticmethod
    def _parse_args(raw: str) -> dict:
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
