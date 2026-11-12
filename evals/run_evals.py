from __future__ import annotations

import json
import re
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from app import config
from app.agent import Agent
from app.db import Database
from app.knowledge import FAQ
from app.llm import build_llm

ROOT = Path(__file__).resolve().parent
FIXED_NOW = datetime(2026, 11, 3, 10, 0)


def run_case(case: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        llm = build_llm()
        agent = Agent(Database(Path(tmp) / "eval.db"), FAQ(config.FAQ_PATH), llm, now=lambda: FIXED_NOW)
        sid = "eval-" + uuid.uuid4().hex[:12]
        replies, used, handoff, error = [], set(), False, False
        for text in case["messages"]:
            result = agent.reply(sid, text)
            replies.append(result.reply)
            used.update(result.tools_used)
            handoff = result.handoff
            error = error or result.error

    problems = []
    if error:
        problems.append("erro do modelo/API")
    for tool in case.get("expect_tools", []):
        if tool not in used:
            problems.append(f"não chamou {tool}")
    for tool in case.get("forbid_tools", []):
        if tool in used:
            problems.append(f"chamou {tool} indevidamente")
    for pattern in case.get("forbid_regex", []):
        if any(re.search(pattern, r, re.I) for r in replies):
            problems.append(f"resposta casa com /{pattern}/")
    if case.get("expect_handoff") is not None and handoff != case["expect_handoff"]:
        problems.append(f"handoff esperado={case['expect_handoff']}, obtido={handoff}")
    return {"name": case["name"], "passed": not problems, "problems": problems,
            "tools": sorted(used), "replies": replies}


def main() -> int:
    if not config.LLM_API_KEY:
        print("Defina LLM_API_KEY no .env antes de rodar a avaliação.")
        return 1
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        r = run_case(case)
        results.append(r)
        print(f"{'PASSOU' if r['passed'] else 'FALHOU'}  {r['name']:<32} ferramentas={r['tools']}")
        for p in r["problems"]:
            print(f"        - {p}")
    ok = sum(r["passed"] for r in results)
    print(f"\nTaxa de acerto: {ok}/{len(results)} ({ok / len(results):.0%}) com {config.LLM_MODEL}")
    (ROOT / "last_run.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
