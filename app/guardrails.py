from __future__ import annotations

import re

PRICE_PATTERNS = [
    re.compile(r"r\$\s?\d", re.I),
    re.compile(r"\d[\d\.,]*\s?reais", re.I),
    re.compile(r"\d+\s?%\s?de\s+desconto", re.I),
]

SAFE_PRICE_REPLY = (
    "Os valores dependem de medidas, materiais e acabamentos, então só consigo "
    "passar um orçamento depois da visita técnica, que é gratuita e sem compromisso. "
    "Quer que eu veja um horário para você?"
)


def check_reply(text: str) -> tuple[str, list[str]]:
    for pattern in PRICE_PATTERNS:
        if pattern.search(text):
            return SAFE_PRICE_REPLY, ["price_guard"]
    return text, []
