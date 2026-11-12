import unittest

from app.tools import HORARIOS, ToolRunner
from tests.helpers import NOW, make_env


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.faq = make_env()
        self.tools = ToolRunner(self.db, self.faq, "sessao-1", lambda: NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def other(self, sid="sessao-2"):
        return ToolRunner(self.db, self.faq, sid, lambda: NOW)

    def test_salvar_lead_informa_campos_faltando(self):
        r = self.tools.run("salvar_lead", {"ambiente": "cozinha"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["lead"], {"ambiente": "cozinha"})
        self.assertEqual(r["campos_faltando"], ["nome", "medidas", "cidade", "prazo"])

    def test_salvar_lead_acumula_dados(self):
        self.tools.run("salvar_lead", {"nome": "Carlos"})
        r = self.tools.run("salvar_lead", {"cidade": "Canoas", "prazo": "2 meses"})
        self.assertEqual(r["lead"]["nome"], "Carlos")
        self.assertEqual(r["lead"]["cidade"], "Canoas")

    def test_salvar_lead_ignora_campo_vazio_e_nao_apaga_dado(self):
        self.tools.run("salvar_lead", {"nome": "Carlos"})
        r = self.tools.run("salvar_lead", {"nome": "  "})
        self.assertEqual(r["lead"]["nome"], "Carlos")

    def test_faq_encontra_prazo(self):
        r = self.tools.run("consultar_faq", {"pergunta": "qual o prazo de entrega?"})
        self.assertIn("30 a 45 dias", r["resultados"][0]["resposta"])

    def test_faq_encontra_pagamento_por_sinonimo(self):
        r = self.tools.run("consultar_faq", {"pergunta": "vocês aceitam pix?"})
        self.assertIn("Pix", r["resultados"][0]["resposta"])

    def test_faq_preco_nao_traz_valor(self):
        r = self.tools.run("consultar_faq", {"pergunta": "quanto custa uma cozinha?"})
        self.assertNotIn("R$", r["resultados"][0]["resposta"])

    def test_faq_sem_resultado_manda_nao_inventar(self):
        r = self.tools.run("consultar_faq", {"pergunta": "vocês vendem sofá?"})
        self.assertEqual(r["resultados"], [])
        self.assertIn("Não invente", r["aviso"])

    def test_duvida_sem_resposta_e_registrada_sem_duplicar(self):
        self.tools.run("consultar_faq", {"pergunta": "vocês fazem móveis para área externa?"})
        self.tools.run("consultar_faq", {"pergunta": "Vocês fazem móveis para área externa?"})
        gaps = self.db.list_gaps()
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["session_id"], "sessao-1")

    def test_pergunta_respondida_pelo_faq_nao_vira_duvida(self):
        self.tools.run("consultar_faq", {"pergunta": "qual a garantia?"})
        self.assertEqual(self.db.list_gaps(), [])

    def test_depois_de_ensinar_o_agente_passa_a_saber(self):
        pergunta = "vocês fazem móveis para área externa?"
        antes = self.tools.run("consultar_faq", {"pergunta": pergunta})
        self.assertEqual(antes["resultados"], [])
        gap = self.db.list_gaps()[0]
        self.db.teach(gap["question"], "Sim, fazemos com MDF naval resistente à umidade.", gap["id"])
        outro = self.other()
        depois = outro.run("consultar_faq", {"pergunta": "fazem móveis de área externa?"})
        self.assertIn("MDF naval", depois["resultados"][0]["resposta"])
        self.assertEqual(self.db.get_gap(gap["id"])["status"], "respondida")
        self.assertEqual(self.db.list_gaps(), [])

    def test_remover_conhecimento_aprendido_e_descartar_duvida(self):
        self.tools.run("consultar_faq", {"pergunta": "vocês aceitam permuta de móveis usados?"})
        gap = self.db.list_gaps()[0]
        learned_id = self.db.teach(gap["question"], "Resposta errada", gap["id"])
        self.db.delete_learned(learned_id)
        r = self.tools.run("consultar_faq", {"pergunta": "vocês aceitam permuta de móveis usados?"})
        self.assertEqual(r["resultados"], [])
        self.db.add_gap("s", "assunto qualquer")
        gid = self.db.list_gaps()[0]["id"]
        self.db.dismiss_gap(gid)
        self.assertEqual(self.db.get_gap(gid)["status"], "descartada")

    def test_horarios_em_dia_util(self):
        r = self.tools.run("verificar_horarios_disponiveis", {"data": "2026-11-04"})
        self.assertEqual(r["horarios_livres"], HORARIOS)
        self.assertEqual(r["dia_semana"], "quarta-feira")

    def test_horarios_rejeita_fim_de_semana(self):
        r = self.tools.run("verificar_horarios_disponiveis", {"data": "2026-11-07"})
        self.assertIn("segunda a sexta", r["erro"])

    def test_horarios_rejeita_hoje_e_passado(self):
        for d in ("2026-11-03", "2026-11-02"):
            r = self.tools.run("verificar_horarios_disponiveis", {"data": d})
            self.assertIn("a partir de amanhã", r["erro"])

    def test_horarios_rejeita_alem_da_janela(self):
        r = self.tools.run("verificar_horarios_disponiveis", {"data": "2026-12-30"})
        self.assertIn("próximos 14 dias", r["erro"])

    def test_horarios_data_invalida(self):
        r = self.tools.run("verificar_horarios_disponiveis", {"data": "amanhã"})
        self.assertIn("AAAA-MM-DD", r["erro"])

    def test_agendar_exige_nome(self):
        r = self.tools.run("agendar_visita", {"data": "2026-11-04", "horario": "10:00", "endereco": "Rua das Flores, 120"})
        self.assertIn("nome", r["erro"])

    def test_agendar_ok_e_ocupa_horario(self):
        self.tools.run("salvar_lead", {"nome": "Ana"})
        r = self.tools.run("agendar_visita", {"data": "2026-11-04", "horario": "10:00", "endereco": "Rua das Flores, 120"})
        self.assertTrue(r["ok"])
        livres = self.tools.run("verificar_horarios_disponiveis", {"data": "2026-11-04"})["horarios_livres"]
        self.assertNotIn("10:00", livres)

    def test_nao_agenda_horario_ocupado(self):
        for t in (self.tools, self.other()):
            t.run("salvar_lead", {"nome": "Fulano"})
        args = {"data": "2026-11-04", "horario": "10:00", "endereco": "Rua das Flores, 120"}
        self.assertTrue(self.tools.run("agendar_visita", args)["ok"])
        r = self.other().run("agendar_visita", args)
        self.assertEqual(r["erro"], "esse horário já está ocupado")
        self.assertNotIn("10:00", r["horarios_livres"])

    def test_remarcar_libera_horario_antigo(self):
        self.tools.run("salvar_lead", {"nome": "Ana"})
        base = {"data": "2026-11-04", "endereco": "Rua das Flores, 120"}
        self.tools.run("agendar_visita", {**base, "horario": "10:00"})
        self.tools.run("agendar_visita", {**base, "horario": "11:00"})
        livres = self.tools.run("verificar_horarios_disponiveis", {"data": "2026-11-04"})["horarios_livres"]
        self.assertIn("10:00", livres)
        self.assertNotIn("11:00", livres)

    def test_remarcar_para_horario_ocupado_mantem_visita_antiga(self):
        a, b = self.tools, self.other()
        for t in (a, b):
            t.run("salvar_lead", {"nome": "X"})
        base = {"data": "2026-11-04", "endereco": "Rua das Flores, 120"}
        a.run("agendar_visita", {**base, "horario": "10:00"})
        b.run("agendar_visita", {**base, "horario": "11:00"})
        r = a.run("agendar_visita", {**base, "horario": "11:00"})
        self.assertIn("erro", r)
        self.assertEqual(self.db.get_visit("sessao-1")["time"], "10:00")

    def test_horario_e_endereco_invalidos(self):
        self.tools.run("salvar_lead", {"nome": "Ana"})
        r = self.tools.run("agendar_visita", {"data": "2026-11-04", "horario": "10:30", "endereco": "Rua das Flores, 120"})
        self.assertIn("horário inválido", r["erro"])
        r = self.tools.run("agendar_visita", {"data": "2026-11-04", "horario": "10:00", "endereco": "x"})
        self.assertIn("endereço", r["erro"])

    def test_transferir_marca_handoff(self):
        r = self.tools.run("transferir_para_humano", {"motivo": "cliente pediu"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.db.get_session("sessao-1")["handoff_reason"], "cliente pediu")

    def test_ferramenta_desconhecida_e_argumentos_invalidos(self):
        self.assertIn("desconhecida", self.tools.run("apagar_tudo", {})["erro"])
        self.assertIn("inválidos", self.tools.run("consultar_faq", {"foo": 1})["erro"])
        self.assertIn("objeto", self.tools.run("consultar_faq", "texto")["erro"])


if __name__ == "__main__":
    unittest.main()
