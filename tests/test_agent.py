import json
import unittest

from app.agent import MSG_ERROR, MSG_HANDOFF_WAIT, MSG_LIMIT, Agent
from app.guardrails import SAFE_PRICE_REPLY
from app.llm import LLMError
from tests.helpers import NOW, FakeLLM, call, make_env, say

S = "sessao-teste-1"


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.faq = make_env()

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, script, **kw):
        self.llm = FakeLLM(script)
        return Agent(self.db, self.faq, self.llm, now=lambda: NOW, **kw)

    def test_qualifica_lead_e_devolve_resultado_da_ferramenta_ao_modelo(self):
        ag = self.agent([
            call("salvar_lead", {"nome": "Carlos", "ambiente": "cozinha"}),
            say("Prazer, Carlos! Qual a cidade?"),
        ])
        r = ag.reply(S, "Oi, sou o Carlos e quero uma cozinha")
        self.assertEqual(r.reply, "Prazer, Carlos! Qual a cidade?")
        self.assertEqual(r.tools_used, ["salvar_lead"])
        self.assertEqual(self.db.get_lead(S)["nome"], "Carlos")
        tool_msg = [m for m in self.llm.calls[1] if m["role"] == "tool"][0]
        self.assertIn("campos_faltando", tool_msg["content"])

    def test_prompt_traz_data_de_hoje(self):
        ag = self.agent([say("Oi!")])
        ag.reply(S, "oi")
        self.assertIn("03/11/2026", self.llm.calls[0][0]["content"])

    def test_conhecimento_ensinado_chega_ao_modelo_mesmo_depois_de_um_nao_sei(self):
        ag = self.agent([say("Não tenho essa informação, vou registrar sua dúvida."), say("Vendemos sim, sob medida.")])
        ag.reply(S, "vende moveis prontos?")
        self.assertNotIn("já encontrada para a última mensagem", self.llm.calls[0][0]["content"])
        self.db.teach("vende moveis prontos", "Não vendemos móveis prontos, só planejados sob medida.")
        ag.reply(S, "vende móveis prontos?")
        prompt = self.llm.calls[1][0]["content"]
        self.assertIn("já encontrada para a última mensagem", prompt)
        self.assertIn("só planejados sob medida", prompt)

    def test_perguntas_do_faq_fixo_tambem_vem_no_contexto(self):
        ag = self.agent([say("30 a 45 dias.")])
        ag.reply(S, "qual o prazo de entrega?")
        self.assertIn("30 a 45 dias", self.llm.calls[0][0]["content"])

    def test_historico_persiste_entre_turnos(self):
        ag = self.agent([say("Oi! Qual ambiente?"), say("Boa escolha!")])
        ag.reply(S, "oi")
        ag.reply(S, "cozinha")
        roles = [m["role"] for m in self.llm.calls[1] if m["role"] != "system"]
        self.assertEqual(roles, ["user", "assistant", "user"])

    def test_guardrail_substitui_resposta_com_preco(self):
        ag = self.agent([say("A cozinha fica por R$ 15.000, fechado?")])
        r = ag.reply(S, "quanto custa?")
        self.assertEqual(r.reply, SAFE_PRICE_REPLY)
        self.assertEqual(r.blocked, "price_guard")
        salvo = self.db.get_session(S)["messages"][-1]
        self.assertEqual(salvo["content"], SAFE_PRICE_REPLY)

    def test_handoff_silencia_o_agente(self):
        ag = self.agent([call("transferir_para_humano", {"motivo": "cliente pediu"}), say("Chamei um atendente.")])
        r = ag.reply(S, "quero falar com uma pessoa")
        self.assertTrue(r.handoff)
        n = len(self.llm.calls)
        r2 = ag.reply(S, "alguém aí?")
        self.assertEqual(r2.reply, MSG_HANDOFF_WAIT)
        self.assertEqual(r2.blocked, "handoff")
        self.assertEqual(len(self.llm.calls), n)

    def test_limite_de_mensagens_nao_chama_o_modelo(self):
        ag = self.agent([say("a"), say("b")], max_user_messages=2)
        ag.reply(S, "1")
        ag.reply(S, "2")
        r = ag.reply(S, "3")
        self.assertEqual(r.reply, MSG_LIMIT)
        self.assertEqual(r.blocked, "limit")
        self.assertEqual(len(self.llm.calls), 2)

    def test_excesso_de_passos_escala_para_humano(self):
        ag = self.agent([
            call("consultar_faq", {"pergunta": "x"}, "a"),
            call("consultar_faq", {"pergunta": "y"}, "b"),
        ], max_tool_steps=2)
        r = ag.reply(S, "oi")
        self.assertTrue(r.handoff)
        self.assertIn("limite de passos", self.db.get_session(S)["handoff_reason"])

    def test_erro_do_modelo_nao_corrompe_a_sessao(self):
        ag = self.agent([LLMError("boom"), say("Agora foi!")])
        r = ag.reply(S, "oi")
        self.assertTrue(r.error)
        self.assertEqual(r.reply, MSG_ERROR)
        s = self.db.get_session(S)
        self.assertEqual((s["messages"], s["user_msg_count"]), ([], 0))
        self.assertEqual(ag.reply(S, "oi de novo").reply, "Agora foi!")

    def test_tool_call_sem_id_e_normalizada(self):
        sem_id = {"role": "assistant", "content": None, "tool_calls": [
            {"function": {"name": "consultar_faq", "arguments": json.dumps({"pergunta": "garantia"})}}
        ]}
        ag = self.agent([sem_id, say("São 5 anos de garantia.")])
        ag.reply(S, "e a garantia?")
        msgs = self.llm.calls[1]
        assistant = [m for m in msgs if m["role"] == "assistant"][0]
        tool = [m for m in msgs if m["role"] == "tool"][0]
        self.assertTrue(tool["tool_call_id"])
        self.assertEqual(tool["tool_call_id"], assistant["tool_calls"][0]["id"])

    def test_assinatura_de_raciocinio_do_gemini_volta_ao_modelo(self):
        extra = {"google": {"thought_signature": "ASSINATURA-123"}}
        msg = call("consultar_faq", {"pergunta": "garantia"})
        msg["tool_calls"][0]["extra_content"] = extra
        ag = self.agent([msg, say("São 5 anos.")])
        ag.reply(S, "e a garantia?")
        enviado = [m for m in self.llm.calls[1] if m["role"] == "assistant"][0]
        self.assertEqual(enviado["tool_calls"][0]["extra_content"], extra)
        guardado = [m for m in self.db.get_session(S)["messages"] if m.get("tool_calls")][0]
        self.assertEqual(guardado["tool_calls"][0]["extra_content"], extra)

    def test_argumentos_quebrados_viram_erro_para_o_modelo(self):
        quebrado = {"role": "assistant", "content": "", "tool_calls": [
            {"id": "z", "function": {"name": "agendar_visita", "arguments": "{nao e json"}}
        ]}
        ag = self.agent([quebrado, say("Desculpa, vamos de novo.")])
        r = ag.reply(S, "agenda pra mim")
        self.assertEqual(r.reply, "Desculpa, vamos de novo.")
        tool = [m for m in self.llm.calls[1] if m["role"] == "tool"][0]
        self.assertIn("erro", tool["content"])

    def test_entrada_vazia_e_truncada(self):
        ag = self.agent([say("ok")], max_input_chars=10)
        with self.assertRaises(ValueError):
            ag.reply(S, "   ")
        ag.reply(S, "x" * 500)
        user_msg = self.db.get_session(S)["messages"][0]
        self.assertEqual(len(user_msg["content"]), 10)

    def test_fluxo_completo_de_agendamento(self):
        ag = self.agent([
            call("salvar_lead", {"nome": "Ana", "ambiente": "closet", "cidade": "Canoas"}),
            say("Oi, Ana! Quando você quer a visita?"),
            call("verificar_horarios_disponiveis", {"data": "2026-11-04"}),
            say("Amanhã tenho 09h, 10h ou 11h. Qual prefere?"),
            call("agendar_visita", {"data": "2026-11-04", "horario": "10:00", "endereco": "Rua das Flores, 120"}),
            say("Agendado para amanhã, 10h!"),
        ])
        ag.reply(S, "Sou a Ana, quero um closet em Canoas")
        ag.reply(S, "pode ser amanhã")
        r = ag.reply(S, "às 10h, Rua das Flores 120")
        self.assertEqual(r.tools_used, ["agendar_visita"])
        visita = self.db.get_visit(S)
        self.assertEqual((visita["date"], visita["time"]), ("2026-11-04", "10:00"))
        painel = self.db.list_leads()[0]
        self.assertEqual((painel["nome"], painel["visita_hora"]), ("Ana", "10:00"))


if __name__ == "__main__":
    unittest.main()
