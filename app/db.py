from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LEAD_FIELDS = ("nome", "telefone", "ambiente", "estilo", "medidas", "cidade", "prazo", "orcamento")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    messages TEXT NOT NULL DEFAULT '[]',
    handoff_reason TEXT,
    user_msg_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    session_id TEXT PRIMARY KEY,
    nome TEXT, telefone TEXT, ambiente TEXT, estilo TEXT,
    medidas TEXT, cidade TEXT, prazo TEXT, orcamento TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aberta',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learned_faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pergunta TEXT NOT NULL,
    resposta TEXT NOT NULL,
    gap_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    endereco TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(date, time)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_session(self, sid: str) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None:
            return {"id": sid, "messages": [], "handoff_reason": None, "user_msg_count": 0}
        return {
            "id": sid,
            "messages": json.loads(row["messages"]),
            "handoff_reason": row["handoff_reason"],
            "user_msg_count": row["user_msg_count"],
        }

    def save_session(self, sid: str, messages: list, user_msg_count: int) -> None:
        now = _now()
        with self._conn() as c:
            c.execute(
                """INSERT INTO sessions (id, messages, user_msg_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     messages = excluded.messages,
                     user_msg_count = excluded.user_msg_count,
                     updated_at = excluded.updated_at""",
                (sid, json.dumps(messages, ensure_ascii=False), user_msg_count, now, now),
            )

    def set_handoff(self, sid: str, reason: str) -> None:
        now = _now()
        with self._conn() as c:
            c.execute(
                """INSERT INTO sessions (id, handoff_reason, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     handoff_reason = excluded.handoff_reason,
                     updated_at = excluded.updated_at""",
                (sid, reason, now, now),
            )

    def upsert_lead(self, sid: str, fields: dict) -> dict:
        clean = {
            k: str(v).strip()[:200]
            for k, v in fields.items()
            if k in LEAD_FIELDS and v is not None and str(v).strip()
        }
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO leads (session_id, updated_at) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (sid, now),
            )
            if clean:
                sets = ", ".join(f"{k} = ?" for k in clean)
                c.execute(
                    f"UPDATE leads SET {sets}, updated_at = ? WHERE session_id = ?",
                    (*clean.values(), now, sid),
                )
        return self.get_lead(sid)

    def get_lead(self, sid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM leads WHERE session_id = ?", (sid,)).fetchone()
        return dict(row) if row else None

    def list_leads(self, limit: int = 200) -> list[dict]:
        sql = """
            SELECT s.id AS session_id, s.handoff_reason, s.user_msg_count, s.updated_at,
                   l.nome, l.telefone, l.ambiente, l.estilo, l.medidas, l.cidade,
                   l.prazo, l.orcamento,
                   v.date AS visita_data, v.time AS visita_hora, v.endereco AS visita_endereco
            FROM sessions s
            LEFT JOIN leads l ON l.session_id = s.id
            LEFT JOIN visits v ON v.session_id = s.id
            ORDER BY s.updated_at DESC
            LIMIT ?
        """
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, (limit,)).fetchall()]

    def booked_times(self, date: str) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT time FROM visits WHERE date = ?", (date,)).fetchall()
        return {r["time"] for r in rows}

    def create_visit(self, sid: str, date: str, time: str, endereco: str) -> bool:
        try:
            with self._conn() as c:
                c.execute("DELETE FROM visits WHERE session_id = ?", (sid,))
                c.execute(
                    "INSERT INTO visits (session_id, date, time, endereco, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, date, time, endereco[:200], _now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_visit(self, sid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM visits WHERE session_id = ?", (sid,)).fetchone()
        return dict(row) if row else None

    def add_gap(self, sid: str, question: str) -> int:
        question = question.strip()[:300]
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM knowledge_gaps WHERE status = 'aberta' AND lower(question) = lower(?)",
                (question,),
            ).fetchone()
            if row:
                return row["id"]
            cur = c.execute(
                "INSERT INTO knowledge_gaps (session_id, question, created_at) VALUES (?, ?, ?)",
                (sid, question, _now()),
            )
            gap_id = cur.lastrowid
        return gap_id

    def get_gap(self, gap_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM knowledge_gaps WHERE id = ?", (gap_id,)).fetchone()
        return dict(row) if row else None

    def list_gaps(self, status: str = "aberta") -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM knowledge_gaps WHERE status = ? ORDER BY id DESC LIMIT 100", (status,)
            ).fetchall()
        return [dict(r) for r in rows]

    def dismiss_gap(self, gap_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE knowledge_gaps SET status = 'descartada' WHERE id = ?", (gap_id,))

    def teach(self, pergunta: str, resposta: str, gap_id: int | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO learned_faq (pergunta, resposta, gap_id, created_at) VALUES (?, ?, ?, ?)",
                (pergunta.strip()[:300], resposta.strip()[:800], gap_id, _now()),
            )
            learned_id = cur.lastrowid
            if gap_id is not None:
                c.execute("UPDATE knowledge_gaps SET status = 'respondida' WHERE id = ?", (gap_id,))
        return learned_id

    def list_learned(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM learned_faq ORDER BY id DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]

    def delete_learned(self, learned_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM learned_faq WHERE id = ?", (learned_id,))
