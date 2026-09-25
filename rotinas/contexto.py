"""Contexto de uma execução (pelo terminal ou pela fila)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import registro


@dataclass
class Contexto:
    """Onde gravar prints, XML e relatórios desta execução, e em que modo rodar.

    - ``ensaio``: vai até o passo anterior a publicar (nada sai do PC).
    - ``diagnostico``: salva hierarquia de tela (XML) + print a cada passo.
    """

    pasta_saida: Path
    ensaio: bool = False
    diagnostico: bool = False
    id_pedido: str | None = None
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.pasta_saida = Path(self.pasta_saida)
        self.pasta_saida.mkdir(parents=True, exist_ok=True)

    def arquivo(self, nome: str) -> Path:
        caminho = self.pasta_saida / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        return caminho

    @property
    def log(self) -> logging.Logger:
        return registro.obter("execucao")


def carimbo() -> str:
    """Carimbo de data e hora para nomes de pasta: ``aaaa-mm-dd_hhmm``."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")
