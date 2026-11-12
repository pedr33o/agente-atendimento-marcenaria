from __future__ import annotations

import sys

from . import config
from .db import Database
from .knowledge import FAQ, _tokens


def explain(db: Database, faq: FAQ, phrase: str = "") -> list[str]:
    learned = db.list_learned()
    gaps = db.list_gaps()
    out = [f"Banco de dados: {config.DB_PATH}", "", f"Conhecimento aprendido: {len(learned)}"]
    out += [f"  [{item['id']}] {item['pergunta']}  ->  {item['resposta'][:90]}" for item in learned]
    out += ["", f"Dúvidas ainda abertas (sem resposta): {len(gaps)}"]
    out += [f"  [{gap['id']}] {gap['question']}" for gap in gaps]
    if not phrase:
        return out

    words = _tokens(phrase)
    out += ["", f"Testando a frase: {phrase!r}", f"  palavras consideradas: {sorted(words)}"]
    found = faq.search(phrase, extra=learned)
    if found:
        out += [f"  ACHOU: {entry['pergunta']}  ->  {entry['resposta'][:90]}" for entry in found]
        return out

    out.append("  NÃO ACHOU nada. Palavras em comum com cada coisa aprendida:")
    if not learned:
        out.append("  (nada foi aprendido ainda: ensine a resposta pelo painel)")
    for item in learned:
        theirs = _tokens(item["pergunta"])
        out.append(f"  [{item['id']}] em comum: {sorted(words & theirs) or 'nenhuma'}  (precisa de {min(2, len(theirs))})")
    return out


def main() -> int:
    phrase = " ".join(sys.argv[1:]).strip()
    for line in explain(Database(config.DB_PATH), FAQ(config.FAQ_PATH), phrase):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
