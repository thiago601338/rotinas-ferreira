"""Tipos de pedido da fila → função que executa.

Cada função tem a assinatura ``tarefa(args: dict, ctx: Contexto) -> dict`` e devolve
um resultado que vira JSON. Erro = exceção (o vigia registra e move para ``fila/erro``).
"""

from __future__ import annotations

import importlib
from typing import Callable

TAREFAS: dict[str, str] = {
    "diagnostico": "rotinas.diagnostico:tarefa",
    "stories.preparar": "rotinas.stories.pasta:tarefa",
    "stories.estoque": "rotinas.stories.estoque:tarefa",
    "stories.montar": "rotinas.stories.pedido:tarefa",
    "stories.postar": "rotinas.stories.bluestacks:tarefa",
    "video.preparar": "rotinas.video.bruto:tarefa",
    "video.planejar": "rotinas.video.plano:tarefa",
    "video.rascunho": "rotinas.video.rascunho:tarefa",
    "video.exportar": "rotinas.video.exportar:tarefa",
    "video.conferir": "rotinas.video.conferencia:tarefa",
}


class TipoDesconhecido(KeyError):
    pass


def resolver(alvo: str) -> Callable:
    modulo, funcao = alvo.split(":", 1)
    return getattr(importlib.import_module(modulo), funcao)


def funcao_da_tarefa(tipo: str) -> Callable:
    if tipo not in TAREFAS:
        raise TipoDesconhecido(f"Tipo de pedido desconhecido: '{tipo}'. Tipos válidos: {', '.join(sorted(TAREFAS))}")
    return resolver(TAREFAS[tipo])
