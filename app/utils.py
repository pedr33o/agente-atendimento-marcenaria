DIAS_SEMANA = [
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
]


def fmt_date(d) -> str:
    return f"{DIAS_SEMANA[d.weekday()]}, {d:%d/%m/%Y}"
