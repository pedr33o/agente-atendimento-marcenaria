import unittest

from unittest import mock

from app import config
from app.llm import (DUMMY_SIGNATURE, FallbackClient, LLMError, OpenAICompatClient,
                     build_llm, prepare_messages)


class Stub:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FallbackTest(unittest.TestCase):
    def test_usa_o_reserva_quando_o_principal_falha(self):
        principal = Stub(error=LLMError("HTTP 503: alta demanda"))
        reserva = Stub(result={"role": "assistant", "content": "ok"})
        r = FallbackClient([principal, reserva]).chat([{"role": "user", "content": "oi"}])
        self.assertEqual(r["content"], "ok")
        self.assertEqual((principal.calls, reserva.calls), (1, 1))

    def test_nao_chama_o_reserva_se_o_principal_funciona(self):
        principal = Stub(result={"role": "assistant", "content": "a"})
        reserva = Stub(result={"role": "assistant", "content": "b"})
        self.assertEqual(FallbackClient([principal, reserva]).chat([])["content"], "a")
        self.assertEqual(reserva.calls, 0)

    def test_falha_quando_todos_falham(self):
        a, b = Stub(error=LLMError("a")), Stub(error=LLMError("b"))
        with self.assertRaises(LLMError) as ctx:
            FallbackClient([a, b]).chat([])
        self.assertEqual(str(ctx.exception), "b")


def historico(extra=None):
    chamada = {"id": "c1", "type": "function", "function": {"name": "consultar_faq", "arguments": "{}"}}
    if extra:
        chamada["extra_content"] = extra
    return [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "", "tool_calls": [chamada]}]


class PrepareMessagesTest(unittest.TestCase):
    def test_gemini_mantem_a_assinatura_real(self):
        real = {"google": {"thought_signature": "REAL"}}
        out = prepare_messages(historico(real), gemini=True)
        self.assertEqual(out[1]["tool_calls"][0]["extra_content"], real)

    def test_gemini_injeta_assinatura_neutra_quando_falta(self):
        out = prepare_messages(historico(), gemini=True)
        sig = out[1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
        self.assertEqual(sig, DUMMY_SIGNATURE)

    def test_outros_provedores_nao_recebem_o_campo_do_google(self):
        out = prepare_messages(historico({"google": {"thought_signature": "REAL"}}), gemini=False)
        self.assertNotIn("extra_content", out[1]["tool_calls"][0])

    def test_nao_altera_o_historico_original(self):
        original = historico()
        prepare_messages(original, gemini=True)
        self.assertNotIn("extra_content", original[1]["tool_calls"][0])


class CircuitBreakerTest(unittest.TestCase):
    def setUp(self):
        self.t = [0.0]
        self.ok = {"role": "assistant", "content": "ok"}

    def client(self, principal, reserva, cooldown=60):
        return FallbackClient([principal, reserva], cooldown=cooldown, clock=lambda: self.t[0])

    def test_modelo_sobrecarregado_fica_em_pausa_e_vai_direto_ao_reserva(self):
        principal = Stub(error=LLMError("HTTP 503", status=503, retryable=True))
        reserva = Stub(result=self.ok)
        fb = self.client(principal, reserva)
        fb.chat([]); fb.chat([]); fb.chat([])
        self.assertEqual(principal.calls, 1)
        self.assertEqual(reserva.calls, 3)

    def test_depois_da_pausa_o_principal_e_testado_de_novo(self):
        principal = Stub(error=LLMError("HTTP 503", status=503, retryable=True))
        reserva = Stub(result=self.ok)
        fb = self.client(principal, reserva, cooldown=60)
        fb.chat([])
        self.t[0] = 61
        fb.chat([])
        self.assertEqual(principal.calls, 2)

    def test_principal_volta_a_ser_usado_quando_se_recupera(self):
        principal = Stub(error=LLMError("HTTP 503", status=503, retryable=True))
        reserva = Stub(result=self.ok)
        fb = self.client(principal, reserva, cooldown=60)
        fb.chat([])
        principal.error, principal.result = None, {"role": "assistant", "content": "principal"}
        self.t[0] = 61
        self.assertEqual(fb.chat([])["content"], "principal")

    def test_erro_do_pedido_nao_poe_o_modelo_em_pausa(self):
        principal = Stub(error=LLMError("HTTP 400", status=400, retryable=False))
        reserva = Stub(result=self.ok)
        fb = self.client(principal, reserva)
        fb.chat([]); fb.chat([])
        self.assertEqual(principal.calls, 2)

    def test_se_todos_estiverem_em_pausa_ainda_tenta(self):
        a = Stub(error=LLMError("HTTP 503", status=503, retryable=True))
        b = Stub(error=LLMError("HTTP 503", status=503, retryable=True))
        fb = self.client(a, b)
        with self.assertRaises(LLMError):
            fb.chat([])
        b.error, b.result = None, self.ok
        self.assertEqual(fb.chat([])["content"], "ok")

    def test_cooldown_zero_desliga_o_disjuntor(self):
        principal = Stub(error=LLMError("HTTP 503", status=503, retryable=True))
        reserva = Stub(result=self.ok)
        fb = self.client(principal, reserva, cooldown=0)
        fb.chat([]); fb.chat([])
        self.assertEqual(principal.calls, 2)


GOOGLE = "https://generativelanguage.googleapis.com/v1beta/openai"


class SpeedSettingsTest(unittest.TestCase):
    def test_esforco_de_raciocinio_vai_so_para_o_google(self):
        msgs = [{"role": "user", "content": "oi"}]
        g = OpenAICompatClient(GOOGLE, "k", "m", reasoning_effort="low")
        outro = OpenAICompatClient("https://api.groq.com/openai/v1", "k", "m", reasoning_effort="low")
        self.assertEqual(g._payload(msgs, None)["reasoning_effort"], "low")
        self.assertNotIn("reasoning_effort", outro._payload(msgs, None))

    def test_sem_esforco_configurado_nao_envia_o_campo(self):
        c = OpenAICompatClient(GOOGLE, "k", "m")
        self.assertNotIn("reasoning_effort", c._payload([], None))

    def test_com_reserva_o_principal_nao_insiste(self):
        with mock.patch.object(config, "LLM_FALLBACK_MODEL", "reserva"), \
             mock.patch.object(config, "LLM_RETRIES", ""):
            llm = build_llm()
        self.assertEqual(llm.clients[0].retries, 0)

    def test_sem_reserva_mantem_tentativas_e_respeita_o_ajuste_manual(self):
        with mock.patch.object(config, "LLM_FALLBACK_MODEL", ""), mock.patch.object(config, "LLM_RETRIES", ""):
            self.assertEqual(build_llm().retries, 2)
        with mock.patch.object(config, "LLM_FALLBACK_MODEL", ""), mock.patch.object(config, "LLM_RETRIES", "1"):
            self.assertEqual(build_llm().retries, 1)

    def test_timeout_vem_da_configuracao(self):
        with mock.patch.object(config, "LLM_FALLBACK_MODEL", ""), mock.patch.object(config, "LLM_TIMEOUT", 12.0):
            self.assertEqual(build_llm().timeout, 12.0)


if __name__ == "__main__":
    unittest.main()
