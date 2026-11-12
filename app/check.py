from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

from . import config
from .llm import LLMError, OpenAICompatClient

DICAS = {
    400: "Pedido recusado. Em geral é o nome do modelo (ou a chave) incorreto.",
    401: "Chave inválida ou não reconhecida. Gere outra no Google AI Studio e confira o .env.",
    403: "Chave sem permissão para esse modelo/serviço. Gere uma nova ou escolha outro modelo.",
    404: "Esse modelo não existe (ou não está liberado) para a sua conta. Troque LLM_MODEL por um da lista abaixo.",
    429: "Limite de uso atingido (por minuto ou por dia). Espere um pouco ou use outro modelo.",
    500: "Erro interno do provedor. Tente de novo em instantes.",
    503: "Modelo sobrecarregado no provedor (não é erro seu). Tente outro modelo da lista abaixo.",
}


def diagnose(message: str) -> str:
    found = re.search(r"HTTP (\d{3})", message)
    if found:
        code = int(found.group(1))
        return DICAS.get(code, f"Erro HTTP {code}. Leia a mensagem acima.")
    if any(w in message for w in ("URLError", "Timeout", "timed out", "getaddrinfo")):
        return "Sem conexão com o provedor: confira a internet, o antivírus, a VPN ou o proxy."
    return "Erro inesperado. Leia a mensagem acima."


def key_problem(key: str) -> str | None:
    key = key.strip()
    if not key:
        return "LLM_API_KEY está vazia. Cole a sua chave no arquivo .env (não no .env.example)."
    if key.startswith("cole_") or "sua_chave" in key:
        return "LLM_API_KEY ainda tem o texto de exemplo. Troque pela chave de verdade."
    if " " in key or key.startswith(("'", '"')):
        return "A chave tem espaços ou aspas. Cole só a chave, sem aspas e sem espaços."
    return None


def test_model(label: str, base_url: str, api_key: str, model: str) -> bool:
    print(f"\n[{label}] modelo: {model}")
    client = OpenAICompatClient(base_url, api_key, model, timeout=30, retries=0)
    start = time.time()
    try:
        reply = client.chat([{"role": "user", "content": "Responda apenas: ok"}])
    except LLMError as exc:
        print(f"  FALHOU: {str(exc)[:400]}")
        print(f"  Diagnóstico: {diagnose(str(exc))}")
        return False
    print(f"  OK em {time.time() - start:.1f}s. Resposta: {(reply.get('content') or '').strip()[:60]!r}")
    return True


def list_models(base_url: str, api_key: str) -> list[str]:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key or 'none'}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [str(m.get("id", "")).removeprefix("models/") for m in data.get("data", [])]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return []
    return sorted(i for i in ids if i)


def main() -> int:
    print("Diagnóstico da conexão com o modelo")
    print(f"  endereço : {config.LLM_BASE_URL}")
    print(f"  principal: {config.LLM_MODEL}")
    print(f"  reserva  : {config.LLM_FALLBACK_MODEL or '(não configurado)'}")
    print(f"  chave    : {'definida' if config.LLM_API_KEY else 'VAZIA'}")

    problem = key_problem(config.LLM_API_KEY)
    if problem and "localhost" not in config.LLM_BASE_URL:
        print(f"\nPROBLEMA: {problem}")
        return 1

    ok = test_model("principal", config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL)
    if config.LLM_FALLBACK_MODEL:
        ok = test_model(
            "reserva",
            config.LLM_FALLBACK_BASE_URL or config.LLM_BASE_URL,
            config.LLM_FALLBACK_API_KEY or config.LLM_API_KEY,
            config.LLM_FALLBACK_MODEL,
        ) or ok

    models = list_models(config.LLM_BASE_URL, config.LLM_API_KEY)
    if models:
        print("\nModelos que a sua chave enxerga (copie um nome para LLM_MODEL no .env):")
        for name in models[:60]:
            print(f"  {name}")
    else:
        print("\n(Não consegui listar os modelos dessa chave.)")
    print("\nResultado:", "pelo menos um modelo respondeu." if ok else "nenhum modelo respondeu.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
