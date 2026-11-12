import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import create_app
except ImportError:
    TestClient = None

from app.agent import Agent
from app.ratelimit import DailyBudget, RateLimiter
from tests.helpers import NOW, FakeLLM, make_env, say

SID = "sessao-api-123"


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.faq = make_env()

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, script=None, **kw):
        agent = Agent(self.db, self.faq, FakeLLM(script or [say("Olá!")] * 5), now=lambda: NOW)
        return TestClient(create_app(agent=agent, **kw))

    def test_chat_ok(self):
        r = self.client().post("/api/chat", json={"session_id": SID, "message": "oi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reply"], "Olá!")

    def test_valida_entrada(self):
        c = self.client()
        self.assertEqual(c.post("/api/chat", json={"session_id": "curto", "message": "oi"}).status_code, 422)
        self.assertEqual(c.post("/api/chat", json={"session_id": SID, "message": ""}).status_code, 422)

    def test_rate_limit(self):
        c = self.client(limiter=RateLimiter(max_calls=1, window=60))
        self.assertEqual(c.post("/api/chat", json={"session_id": SID, "message": "oi"}).status_code, 200)
        self.assertEqual(c.post("/api/chat", json={"session_id": SID, "message": "oi"}).status_code, 429)

    def test_limite_diario_global_responde_503_com_codigo(self):
        c = self.client(budget=DailyBudget(1))
        self.assertEqual(c.post("/api/chat", json={"session_id": SID, "message": "oi"}).status_code, 200)
        r = c.post("/api/chat", json={"session_id": SID, "message": "oi"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"]["code"], "demo_limit")

    def test_info_traz_links_opcionais(self):
        info = self.client().get("/api/info").json()
        self.assertIn("video_url", info)
        self.assertIn("repo_url", info)

    def test_historico_e_painel(self):
        c = self.client()
        c.post("/api/chat", json={"session_id": SID, "message": "oi"})
        hist = c.get(f"/api/sessions/{SID}").json()["messages"]
        self.assertEqual([m["role"] for m in hist], ["user", "assistant"])
        self.db.upsert_lead(SID, {"nome": "Ana", "ambiente": "closet"})
        ficha = c.get(f"/api/sessions/{SID}").json()
        self.assertEqual(ficha["lead"]["nome"], "Ana")
        self.assertIsNone(ficha["visit"])
        self.assertEqual(len(c.get("/api/leads").json()["leads"]), 1)

    def test_painel_protegido_por_token(self):
        c = self.client(panel_token="segredo")
        self.assertEqual(c.get("/api/leads").status_code, 401)
        self.assertEqual(c.get("/api/leads?token=errado").status_code, 401)
        self.assertEqual(c.get("/api/leads?token=segredo").status_code, 200)
        self.assertEqual(c.get("/api/leads", headers={"x-panel-token": "segredo"}).status_code, 200)

    def test_professor_ensina_o_agente_pela_api(self):
        c = self.client(panel_token="segredo")
        gid = self.db.add_gap("s1", "vocês fazem móveis para área externa?")
        auth = {"x-panel-token": "segredo"}
        self.assertEqual(c.get("/api/gaps").status_code, 401)
        self.assertEqual(len(c.get("/api/gaps", headers=auth).json()["gaps"]), 1)
        r = c.post(f"/api/gaps/{gid}/answer", json={"resposta": "Sim, com MDF naval."})
        self.assertEqual(r.status_code, 401)
        r = c.post(f"/api/gaps/{gid}/answer", json={"resposta": "Sim, com MDF naval."}, headers=auth)
        self.assertEqual(r.status_code, 200)
        body = c.get("/api/gaps", headers=auth).json()
        self.assertEqual(body["gaps"], [])
        self.assertEqual(len(body["learned"]), 1)
        self.assertEqual(c.post("/api/gaps/999/answer", json={"resposta": "abc"}, headers=auth).status_code, 404)

    def test_serve_o_chat(self):
        r = self.client().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
