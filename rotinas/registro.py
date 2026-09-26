"""Logs em português, sempre sem segredos."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from . import config

FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATA = "%Y-%m-%d %H:%M:%S"

_PADROES = [
    # JWT (chaves do Supabase são JWT) e tokens longos
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(bearer)(\s+)([^\s,;\"'\\{}]{6,})"),
    re.compile(r"(?i)\b(apikey|api_key|authorization|token|senha|password|supabase_key)\b(\s*[:=]\s*)([^\s,;\"'\\]{6,})"),
    re.compile(r"sb_(?:secret|publishable)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
]


def ocultar(texto: str) -> str:
    """Troca por ``***`` qualquer valor do ``.env`` e padrões de token."""
    if not texto:
        return texto
    for valor in config.valores_secretos():
        texto = texto.replace(valor, "***")
    for padrao in _PADROES:
        if padrao.groups >= 3:
            texto = padrao.sub(lambda m: f"{m.group(1)}{m.group(2)}***", texto)
        else:
            texto = padrao.sub("***", texto)
    return texto


def ocultar_estrutura(dados):
    """Aplica :func:`ocultar` em todas as strings de um dict/lista (sem mexer na estrutura)."""
    if isinstance(dados, str):
        return ocultar(dados)
    if isinstance(dados, dict):
        return {ocultar(str(k)) if isinstance(k, str) else k: ocultar_estrutura(v) for k, v in dados.items()}
    if isinstance(dados, (list, tuple)):
        return [ocultar_estrutura(v) for v in dados]
    return dados


class FiltroSegredos(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            mensagem = record.getMessage()
        except Exception:  # pragma: no cover - mensagem malformada
            return True
        record.msg = ocultar(mensagem)
        record.args = ()
        return True


def _console_utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def configurar(arquivo: Path | None = None, nivel: int = logging.INFO, console: bool = True) -> logging.Logger:
    """Configura o logger raiz ``rotinas``. Pode ser chamado de novo para trocar o arquivo."""
    log = logging.getLogger("rotinas")
    log.setLevel(nivel)
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    formatador = logging.Formatter(FORMATO, DATA)
    filtro = FiltroSegredos()
    if console and sys.stderr is not None:
        _console_utf8()
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(formatador)
        h.addFilter(filtro)
        log.addHandler(h)
    if arquivo:
        Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(arquivo, encoding="utf-8")
        h.setFormatter(formatador)
        h.addFilter(filtro)
        log.addHandler(h)
    log.propagate = False
    return log


def anexar_arquivo(arquivo: Path) -> logging.Handler:
    """Adiciona um arquivo de log extra (ex.: o log de um pedido da fila). Devolve o handler para remover depois."""
    log = logging.getLogger("rotinas")
    Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(arquivo, encoding="utf-8")
    h.setFormatter(logging.Formatter(FORMATO, DATA))
    h.addFilter(FiltroSegredos())
    log.addHandler(h)
    if log.level == logging.NOTSET or log.level > logging.INFO:
        log.setLevel(logging.INFO)
    return h


def remover(handler: logging.Handler) -> None:
    logging.getLogger("rotinas").removeHandler(handler)
    handler.close()


def obter(nome: str) -> logging.Logger:
    """Logger filho, ex.: ``obter("stories.pasta")`` → ``rotinas.stories.pasta``."""
    return logging.getLogger(f"rotinas.{nome}")
