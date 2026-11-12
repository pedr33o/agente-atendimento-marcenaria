import unittest

from app.check import diagnose, key_problem


class CheckTest(unittest.TestCase):
    def test_diagnostico_por_codigo(self):
        self.assertIn("sobrecarregado", diagnose("HTTP 503: alta demanda"))
        self.assertIn("não existe", diagnose("HTTP 404: model not found"))
        self.assertIn("Limite", diagnose("HTTP 429: quota"))
        self.assertIn("Chave", diagnose("HTTP 401: x"))

    def test_diagnostico_de_rede(self):
        self.assertIn("conexão", diagnose("URLError: <urlopen error getaddrinfo failed>"))

    def test_problemas_comuns_de_chave(self):
        self.assertIn("vazia", key_problem(""))
        self.assertIn("exemplo", key_problem("cole_sua_chave_aqui"))
        self.assertIn("espaços", key_problem("abc def"))
        self.assertIsNone(key_problem("AbC123xyz"))


if __name__ == "__main__":
    unittest.main()
