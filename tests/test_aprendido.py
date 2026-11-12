import unittest

from app.aprendido import explain
from app.knowledge import _tokens
from tests.helpers import make_env


class StemTest(unittest.TestCase):
    def test_variacoes_da_mesma_palavra_se_encontram(self):
        grupos = [
            ["móvel", "móveis", "moveis"],
            ["pronto", "pronta", "prontos", "prontas"],
            ["vende", "venda", "vendem", "vendas"],
            ["cozinha", "cozinhas"],
            ["valor", "valores"],
            ["atende", "atendem"],
        ]
        for grupo in grupos:
            self.assertEqual(len({frozenset(_tokens(p)) for p in grupo}), 1, grupo)


class ExplainTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.faq = make_env()
        self.db.teach("vende moveis prontos", "Não vendemos móveis prontos, só planejados sob medida.")

    def tearDown(self):
        self.tmp.cleanup()

    def test_frase_parecida_agora_acha_o_que_foi_ensinado(self):
        for frase in ("vocês têm móvel pronto?", "vendem móveis prontos?", "vende móvel pronto"):
            texto = "\n".join(explain(self.db, self.faq, frase))
            self.assertIn("ACHOU", texto, frase)
            self.assertIn("só planejados", texto, frase)

    def test_diagnostico_explica_quando_nao_acha(self):
        texto = "\n".join(explain(self.db, self.faq, "tem sofá para levar?"))
        self.assertIn("NÃO ACHOU", texto)
        self.assertIn("precisa de 2", texto)

    def test_lista_o_que_foi_aprendido_e_as_duvidas_abertas(self):
        self.db.add_gap("s1", "aceitam permuta?")
        texto = "\n".join(explain(self.db, self.faq))
        self.assertIn("Conhecimento aprendido: 1", texto)
        self.assertIn("aceitam permuta?", texto)


if __name__ == "__main__":
    unittest.main()
