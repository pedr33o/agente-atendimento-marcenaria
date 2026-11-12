from __future__ import annotations

import inspect
import logging
from datetime import date, datetime, timedelta

from .db import Database
from .knowledge import FAQ
from .utils import DIAS_SEMANA

log = logging.getLogger("agente.tools")

HORARIOS = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00", "16:00"]
DIAS_JANELA = 14
CAMPOS_OBRIGATORIOS = ("nome", "ambiente", "medidas", "cidade", "prazo")


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


TOOL_SCHEMAS = [
    _fn(
        "salvar_lead",
        "Salva ou atualiza os dados do cliente. Chame assim que o cliente informar qualquer dado novo. "
        "Envie apenas os campos que ele informou. Retorna os campos que ainda faltam.",
        {
            "nome": _str("Nome do cliente"),
            "telefone": _str("Telefone, se o cliente informar"),
            "ambiente": _str("Ambiente a planejar (cozinha, quarto, closet...)"),
            "estilo": _str("Estilo desejado (moderno, clássico...)"),
            "medidas": _str("Medidas aproximadas, como o cliente disse"),
            "cidade": _str("Cidade do cliente"),
            "prazo": _str("Prazo desejado, como o cliente disse"),
            "orcamento": _str("Faixa de investimento que o cliente mencionou"),
        },
    ),
    _fn(
        "consultar_faq",
        "Busca na base da empresa: materiais, prazos, garantia, pagamento, cidades atendidas, "
        "horários, visita técnica. Use antes de afirmar qualquer fato sobre a empresa.",
        {"pergunta": _str("A dúvida do cliente, em poucas palavras")},
        ["pergunta"],
    ),
    _fn(
        "verificar_horarios_disponiveis",
        "Lista os horários livres para visita técnica em uma data (somente dias úteis, "
        "a partir de amanhã, nos próximos 14 dias).",
        {"data": _str("Data no formato AAAA-MM-DD")},
        ["data"],
    ),
    _fn(
        "agendar_visita",
        "Agenda (ou remarca) a visita técnica do cliente. Só chame depois de confirmar "
        "data, horário e endereço com o cliente, e depois de ter o nome dele salvo.",
        {
            "data": _str("Data no formato AAAA-MM-DD"),
            "horario": _str("Horário no formato HH:MM, um dos horários livres"),
            "endereco": _str("Endereço onde será a visita"),
        },
        ["data", "horario", "endereco"],
    ),
    _fn(
        "transferir_para_humano",
        "Passa a conversa para um atendente humano. Use quando o cliente pedir, reclamar, "
        "quiser negociar valor ou quando você não conseguir resolver.",
        {"motivo": _str("Motivo da transferência, em uma frase")},
        ["motivo"],
    ),
]

TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}


class ToolRunner:
    def __init__(self, db: Database, faq: FAQ, session_id: str, now):
        self.db = db
        self.faq = faq
        self.sid = session_id
        self.now = now

    def run(self, name: str, args) -> dict:
        if name not in TOOL_NAMES:
            return {"erro": f"ferramenta desconhecida: {name}"}
        if not isinstance(args, dict):
            return {"erro": "argumentos devem ser um objeto JSON"}
        handler = getattr(self, f"_{name}")
        try:
            inspect.signature(handler).bind(**args)
        except TypeError as exc:
            return {"erro": f"argumentos inválidos: {exc}"}
        try:
            return handler(**args)
        except Exception:
            log.exception("falha na ferramenta %s", name)
            return {"erro": "falha interna na ferramenta; tente de novo ou chame um atendente"}

    def _salvar_lead(self, nome=None, telefone=None, ambiente=None, estilo=None,
                     medidas=None, cidade=None, prazo=None, orcamento=None) -> dict:
        lead = self.db.upsert_lead(self.sid, {
            "nome": nome, "telefone": telefone, "ambiente": ambiente, "estilo": estilo,
            "medidas": medidas, "cidade": cidade, "prazo": prazo, "orcamento": orcamento,
        })
        faltando = [c for c in CAMPOS_OBRIGATORIOS if not lead.get(c)]
        salvo = {k: v for k, v in lead.items() if k not in ("session_id", "updated_at") and v}
        return {"ok": True, "lead": salvo, "campos_faltando": faltando}

    def _consultar_faq(self, pergunta: str) -> dict:
        found = self.faq.search(pergunta, extra=self.db.list_learned())
        if not found:
            self.db.add_gap(self.sid, pergunta)
            return {
                "resultados": [],
                "aviso": "Nada encontrado na base. Não invente: diga que vai confirmar "
                         "com a equipe (a dúvida já foi registrada para eles) e ofereça um atendente.",
            }
        return {"resultados": [{"assunto": e["pergunta"], "resposta": e["resposta"]} for e in found]}

    def _verificar_horarios_disponiveis(self, data: str) -> dict:
        d = self._parse_date(data)
        if d is None:
            return {"erro": "data inválida; use o formato AAAA-MM-DD"}
        erro = self._validar_dia(d)
        if erro:
            return {"erro": erro}
        ocupados = self.db.booked_times(d.isoformat())
        livres = [h for h in HORARIOS if h not in ocupados]
        out = {"data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()], "horarios_livres": livres}
        if not livres:
            out["aviso"] = "Sem horários nesse dia; sugira outra data."
        return out

    def _agendar_visita(self, data: str, horario: str, endereco: str) -> dict:
        lead = self.db.get_lead(self.sid)
        if not lead or not lead.get("nome"):
            return {"erro": "Antes de agendar, pergunte o nome do cliente e salve com salvar_lead."}
        d = self._parse_date(data)
        if d is None:
            return {"erro": "data inválida; use o formato AAAA-MM-DD"}
        erro = self._validar_dia(d)
        if erro:
            return {"erro": erro}
        if horario not in HORARIOS:
            return {"erro": f"horário inválido; use um destes: {', '.join(HORARIOS)}"}
        if len((endereco or "").strip()) < 5:
            return {"erro": "endereço incompleto; peça rua, número e bairro ao cliente"}
        if not self.db.create_visit(self.sid, d.isoformat(), horario, endereco.strip()):
            livres = [h for h in HORARIOS if h not in self.db.booked_times(d.isoformat())]
            return {"erro": "esse horário já está ocupado", "horarios_livres": livres}
        return {
            "ok": True,
            "mensagem": "Visita agendada. Confirme data, horário e endereço ao cliente.",
            "data": d.isoformat(),
            "dia_semana": DIAS_SEMANA[d.weekday()],
            "horario": horario,
            "endereco": endereco.strip(),
        }

    def _transferir_para_humano(self, motivo: str) -> dict:
        self.db.set_handoff(self.sid, str(motivo).strip()[:200] or "sem motivo informado")
        return {"ok": True, "mensagem": "Atendente avisado. Informe ao cliente que ele vai continuar."}

    @staticmethod
    def _parse_date(value: str) -> date | None:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _validar_dia(self, d: date) -> str | None:
        hoje = self.now().date()
        if d <= hoje:
            return "só agendamos a partir de amanhã"
        if d > hoje + timedelta(days=DIAS_JANELA):
            return f"a agenda está aberta apenas para os próximos {DIAS_JANELA} dias"
        if d.weekday() >= 5:
            return "as visitas acontecem só de segunda a sexta"
        return None
