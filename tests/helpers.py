import json
import tempfile
from datetime import datetime
from pathlib import Path

from app.db import Database
from app.knowledge import FAQ

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 3, 10, 0)


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(json.loads(json.dumps(messages)))
        if not self.script:
            raise AssertionError("LLM chamado além do roteiro")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def say(text):
    return {"role": "assistant", "content": text}


def call(name, args, call_id="c1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }],
    }


def make_env():
    tmp = tempfile.TemporaryDirectory()
    db = Database(Path(tmp.name) / "test.db")
    faq = FAQ(ROOT / "data" / "faq.json")
    return tmp, db, faq
