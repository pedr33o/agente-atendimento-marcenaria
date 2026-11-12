import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.8-flash")

LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
LLM_RETRIES = os.getenv("LLM_RETRIES", "")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")

LLM_COOLDOWN = float(os.getenv("LLM_COOLDOWN", "60"))

LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
LLM_FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "")
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "")

DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "marcenaria.db"))
FAQ_PATH = os.getenv("FAQ_PATH", str(ROOT / "data" / "faq.json"))

MAX_USER_MESSAGES = int(os.getenv("MAX_USER_MESSAGES", "30"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "800"))
MAX_TOOL_STEPS = int(os.getenv("MAX_TOOL_STEPS", "6"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

DAILY_MESSAGE_LIMIT = int(os.getenv("DAILY_MESSAGE_LIMIT", "300"))

DEMO_VIDEO_URL = os.getenv("DEMO_VIDEO_URL", "")
REPO_URL = os.getenv("REPO_URL", "")

PANEL_TOKEN = os.getenv("PANEL_TOKEN", "")

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Marcenaria Nogueira")
GREETING = (
    f"Oi! Eu sou a Duda, assistente virtual da {BUSINESS_NAME}. "
    "Me conta: que ambiente você quer planejar?"
)
