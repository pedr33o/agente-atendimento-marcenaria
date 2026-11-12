from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("agente.llm")
RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


GEMINI_HOST = "generativelanguage.googleapis.com"
DUMMY_SIGNATURE = "skip_thought_signature_validator"


def prepare_messages(messages: list[dict], gemini: bool) -> list[dict]:
    prepared = json.loads(json.dumps(messages))
    for msg in prepared:
        calls = msg.get("tool_calls") if msg.get("role") == "assistant" else None
        if not calls:
            continue
        if not gemini:
            for call in calls:
                call.pop("extra_content", None)
            continue
        first = calls[0]
        signature = ((first.get("extra_content") or {}).get("google") or {}).get("thought_signature")
        if not signature:
            first["extra_content"] = {"google": {"thought_signature": DUMMY_SIGNATURE}}
    return prepared


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60,
                 retries: int = 2, reasoning_effort: str = ""):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.gemini = GEMINI_HOST in base_url
        self.api_key = api_key or "none"
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.reasoning_effort = reasoning_effort.strip()

    def _payload(self, messages: list[dict], tools: list[dict] | None) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": prepare_messages(messages, self.gemini),
            "temperature": 0.3,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_effort and self.gemini:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        body = json.dumps(self._payload(messages, tools), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

        last: LLMError | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                last = LLMError(f"HTTP {exc.code}: {detail}", status=exc.code,
                                retryable=exc.code in RETRY_STATUS)
                if exc.code not in RETRY_STATUS:
                    raise last from exc
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last = LLMError(f"{type(exc).__name__}: {exc}", retryable=True)
            log.warning("LLM falhou (tentativa %d/%d): %s", attempt + 1, self.retries + 1, last)
            if attempt < self.retries:
                time.sleep(1.5 * (attempt + 1))
        raise last


class FallbackClient:
    def __init__(self, clients, cooldown: float = 60.0, clock=time.monotonic):
        self.clients = list(clients)
        self.cooldown = cooldown
        self.clock = clock
        self._down_until = [0.0] * len(self.clients)
        self._lock = threading.Lock()

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        now = self.clock()
        with self._lock:
            order = [i for i, until in enumerate(self._down_until) if until <= now]
        if not order:
            order = list(range(len(self.clients)))

        last: LLMError | None = None
        for i in order:
            try:
                return self.clients[i].chat(messages, tools)
            except LLMError as exc:
                last = exc
                if exc.retryable and self.cooldown > 0:
                    with self._lock:
                        self._down_until[i] = self.clock() + self.cooldown
                    log.warning("Modelo %d com problema passageiro (%s); em pausa por %.0fs", i + 1, exc, self.cooldown)
                else:
                    log.warning("Modelo %d falhou (%s); tentando o próximo", i + 1, exc)
        raise last


def build_llm():
    has_backup = bool(config.LLM_FALLBACK_MODEL)
    if config.LLM_RETRIES.strip():
        retries = int(config.LLM_RETRIES)
    else:
        retries = 0 if has_backup else 2
    primary = OpenAICompatClient(
        config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL,
        timeout=config.LLM_TIMEOUT, retries=retries,
        reasoning_effort=config.LLM_REASONING_EFFORT,
    )
    if not has_backup:
        return primary
    backup = OpenAICompatClient(
        config.LLM_FALLBACK_BASE_URL or config.LLM_BASE_URL,
        config.LLM_FALLBACK_API_KEY or config.LLM_API_KEY,
        config.LLM_FALLBACK_MODEL,
        timeout=config.LLM_TIMEOUT, retries=1,
        reasoning_effort=config.LLM_REASONING_EFFORT,
    )
    return FallbackClient([primary, backup], cooldown=config.LLM_COOLDOWN)
