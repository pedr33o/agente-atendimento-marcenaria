import unittest

from app.guardrails import SAFE_PRICE_REPLY, check_reply
from datetime import date

from app.ratelimit import DailyBudget, RateLimiter


class GuardrailsTest(unittest.TestCase):
    def test_bloqueia_preco(self):
        for texto in ("Fica em R$ 15.000", "sai por 3000 reais", "te dou 10% de desconto", "r$5"):
            final, v = check_reply(texto)
            self.assertEqual(v, ["price_guard"], texto)
            self.assertEqual(final, SAFE_PRICE_REPLY)

    def test_libera_texto_legitimo_da_faq(self):
        for texto in (
            "Aceitamos Pix e cartão em até 10x.",
            "Em geral, 40% de entrada e o restante na entrega.",
            "De 30 a 45 dias corridos, e 5 anos de garantia.",
        ):
            final, v = check_reply(texto)
            self.assertEqual(v, [], texto)
            self.assertEqual(final, texto)


class RateLimiterTest(unittest.TestCase):
    def test_janela_deslizante(self):
        t = [0.0]
        rl = RateLimiter(max_calls=2, window=60, clock=lambda: t[0])
        self.assertTrue(rl.allow("ip"))
        self.assertTrue(rl.allow("ip"))
        self.assertFalse(rl.allow("ip"))
        self.assertTrue(rl.allow("outro-ip"))
        t[0] = 61
        self.assertTrue(rl.allow("ip"))


class DailyBudgetTest(unittest.TestCase):
    def test_bloqueia_ao_atingir_o_limite_e_zera_no_dia_seguinte(self):
        dia = [date(2026, 11, 3)]
        b = DailyBudget(2, today=lambda: dia[0])
        self.assertTrue(b.take())
        self.assertTrue(b.take())
        self.assertFalse(b.take())
        dia[0] = date(2026, 11, 4)
        self.assertTrue(b.take())

    def test_zero_significa_sem_limite(self):
        b = DailyBudget(0)
        self.assertTrue(all(b.take() for _ in range(1000)))


if __name__ == "__main__":
    unittest.main()
