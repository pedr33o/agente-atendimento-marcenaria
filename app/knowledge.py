from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

STOPWORDS = {
    "que", "qual", "quais", "como", "para", "com", "uma", "uns", "umas", "voce", "voces",
    "vcs", "tem", "posso", "quero", "gostaria", "saber", "sobre", "dos", "das", "nos",
    "nas", "por", "mais", "muito", "meu", "minha", "seu", "sua", "foi", "ser", "tambem",
    "fazer", "tudo", "esse", "essa", "isso", "aqui",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("eis"):
        token = token[:-3] + "el"
    elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    if len(token) > 5 and token.endswith("em"):
        token = token[:-2]
    if len(token) > 4 and token[-1] in "aoe":
        token = token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    return {
        _stem(t)
        for t in re.findall(r"[a-z0-9]+", _norm(text))
        if len(t) > 2 and t not in STOPWORDS
    }


MIN_SCORE = 2


class FAQ:
    def __init__(self, path):
        self.entries = json.loads(Path(path).read_text(encoding="utf-8"))
        self._index = [
            (_tokens(" ".join(e.get("tags", []))), _tokens(e["pergunta"]))
            for e in self.entries
        ]

    def search(self, query: str, top_k: int = 2, extra=()) -> list[dict]:
        q = _tokens(query)
        scored = []
        for entry in extra:
            words = _tokens(entry["pergunta"])
            overlap = len(q & words)
            if overlap >= min(2, len(words)) and overlap > 0:
                scored.append((2 * overlap, entry))
        for entry, (tags, words) in zip(self.entries, self._index):
            score = 2 * len(q & tags) + len(q & words)
            if score >= MIN_SCORE:
                scored.append((score, entry))
        scored.sort(key=lambda s: -s[0])
        return [e for _, e in scored[:top_k]]
