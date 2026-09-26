"""Linha de comando: ``python -m rotinas <comando> [opções]``.

Cada comando aponta para ``modulo:funcao`` com a assinatura ``cli(argv: list[str]) -> int``.
A importação é preguiçosa: um módulo com problema não derruba os outros comandos.
"""

from __future__ import annotations

import sys

from . import __version__, registro
from .tarefas import resolver

COMANDOS: dict[str, tuple[str, str]] = {
    "verificar": ("rotinas.instalacao:cli_verificar", "Confere a instalação e mostra o que está verde e o que falta"),
    "instalar": ("rotinas.instalacao:cli_instalar", "Parte Python do instalar.bat (ffmpeg, adb, pastas, .env, vigia)"),
    "diagnostico": ("rotinas.diagnostico:cli", "Coleta versões, ADB, tela do Instagram e rascunho do CapCut"),
    "testar": ("rotinas.execucao:cli", "Roda um teste real e envia o resultado (execucoes/) pelo git"),
    "vigia": ("rotinas.fila:cli_vigia", "Executa os pedidos da fila (pendente → andamento → feito | erro)"),
    "fila": ("rotinas.fila:cli", "Cria, lista e mostra pedidos da fila"),
    "stories-preparar": ("rotinas.stories.pasta:cli", "A1: nomeia, converte e gera folhas de contato da pasta do dia"),
    "stories-estoque": ("rotinas.stories.estoque:cli", "A2: consulta estoque (só leitura)"),
    "stories-postados": ("rotinas.stories.postados:cli", "A3: consulta o registro de já postados"),
    "stories-recriar": ("rotinas.stories.recriar:cli", "recria foto de várias cores sem a cor sem estoque (API da OpenAI)"),
    "stories-montar": ("rotinas.stories.pedido:cli", "A2–A4: corta sem estoque e já postados, monta links e grava o pedido"),
    "stories-postar": ("rotinas.stories.bluestacks:cli", "A5: posta pelo BlueStacks (--ensaio, --diagnostico)"),
    "stories-relatorio": ("rotinas.stories.relatorio:cli", "A6: relatório de um pedido e JS de conferência"),
    "video-preparar": ("rotinas.video.bruto:cli", "B1: inventário, tomadas, silêncios, transcrição, batidas, folhas"),
    "video-receitas": ("rotinas.video.receitas:cli", "B2: lista e valida as receitas"),
    "video-planejar": ("rotinas.video.plano:cli", "B2: monta o plano da linha do tempo a partir de receita + escolhas"),
    "video-rascunho": ("rotinas.video.rascunho:cli", "B3: gera o rascunho do CapCut a partir do plano"),
    "video-exportar": ("rotinas.video.exportar:cli", "B4: exporta pelo CapCut (atalhos)"),
    "video-conferir": ("rotinas.video.conferencia:cli", "B4: confere o arquivo exportado"),
}


def ajuda() -> str:
    largura = max(len(n) for n in COMANDOS)
    linhas = [f"Rotinas Ferreira {__version__}", "", "Uso: python -m rotinas <comando> [opções]", "", "Comandos:"]
    linhas += [f"  {n.ljust(largura)}  {d}" for n, (_, d) in COMANDOS.items()]
    linhas += ["", "Ajuda de um comando: python -m rotinas <comando> --help"]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "ajuda", "help"):
        print(ajuda())
        return 0
    if argv[0] in ("--versao", "--version"):
        print(__version__)
        return 0
    nome, resto = argv[0], argv[1:]
    if nome not in COMANDOS:
        print(f"Comando desconhecido: {nome}\n", file=sys.stderr)
        print(ajuda(), file=sys.stderr)
        return 2
    if not registro.logging.getLogger("rotinas").handlers:
        registro.configurar()
    funcao = resolver(COMANDOS[nome][0])
    try:
        return int(funcao(resto) or 0)
    except KeyboardInterrupt:
        print("Interrompido.", file=sys.stderr)
        return 130
