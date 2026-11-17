"""Regras persistidas em `rules.json`. No máximo uma regra ativa por objeto."""

import logging
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from homemind.contracts.regras import Acao, AcaoLampada, AcaoTomada, Rule
from homemind.contracts.visao import ClasseObjeto

log = logging.getLogger(__name__)
_lista = TypeAdapter(list[Rule])

PREDEFINIDAS = [
    Rule(
        id="pausa",
        nome="Modo pausa",
        objeto="caneca",
        acoes=[AcaoLampada(ligada=True, cor="branco_quente", brilho=30)],
    ),
    Rule(
        id="leitura",
        nome="Modo leitura",
        objeto="livro",
        acoes=[
            AcaoLampada(ligada=True, cor="branco_quente", brilho=40),
            AcaoTomada(ligada=True),
        ],
    ),
    Rule(
        id="cinema",
        nome="Modo cinema",
        objeto="comando",
        acoes=[
            AcaoLampada(ligada=True, cor="azul", brilho=10),
            AcaoTomada(ligada=True),
        ],
    ),
]

_ARTIGO = {"caneca": "a caneca", "livro": "o livro", "comando": "o comando"}


def descrever_acao(a: Acao) -> str:
    if a.dispositivo == "tomada":
        return "liga a tomada" if a.ligada else "desliga a tomada"
    if not a.ligada:
        return "desliga a luz"
    partes = ["liga a luz"]
    if a.cor:
        partes.append(a.cor.replace("_", " "))
    if a.brilho is not None:
        partes.append(f"a {a.brilho}%")
    return " ".join(partes)


def descrever(regra: Rule) -> str:
    acoes = ", ".join(descrever_acao(a) for a in regra.acoes)
    return f"Ao levantar {_ARTIGO[regra.objeto]}, ativa «{regra.nome}»: {acoes}."


class RulesStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._regras: list[Rule] = []

    def carregar(self) -> None:
        if not self.path.exists():
            self._regras = [r.model_copy() for r in PREDEFINIDAS]
            self._gravar()
            return
        try:
            self._regras = _lista.validate_json(self.path.read_bytes())
        except ValidationError:
            # Ficheiro inválido: não arrancar sem regras; mantém o ficheiro para análise.
            log.exception("rules.json inválido; a usar regras predefinidas")
            self._regras = [r.model_copy() for r in PREDEFINIDAS]

    def listar(self) -> list[Rule]:
        return list(self._regras)

    def obter(self, regra_id: str) -> Rule | None:
        return next((r for r in self._regras if r.id == regra_id), None)

    def ativa_para(self, objeto: ClasseObjeto) -> Rule | None:
        return next((r for r in self._regras if r.objeto == objeto and r.enabled), None)

    def guardar(self, regra: Rule) -> Rule:
        """Cria ou substitui (mesmo id). Uma regra ativa desativa as outras do mesmo objeto."""
        self._regras = [r for r in self._regras if r.id != regra.id] + [regra]
        if regra.enabled:
            self._desativar_outras(regra)
        self._gravar()
        return regra

    def definir_ativa(self, regra_id: str, ativa: bool) -> Rule | None:
        regra = self.obter(regra_id)
        if regra is None:
            return None
        regra.enabled = ativa
        if ativa:
            self._desativar_outras(regra)
        self._gravar()
        return regra

    def apagar(self, regra_id: str) -> bool:
        antes = len(self._regras)
        self._regras = [r for r in self._regras if r.id != regra_id]
        if len(self._regras) == antes:
            return False
        self._gravar()
        return True

    def _desativar_outras(self, regra: Rule) -> None:
        for r in self._regras:
            if r.objeto == regra.objeto and r.id != regra.id:
                r.enabled = False

    def _gravar(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(_lista.dump_json(self._regras, indent=2))
        tmp.replace(self.path)
