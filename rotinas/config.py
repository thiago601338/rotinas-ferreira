"""Leitura de ``config/*.json``, do ``.env`` e das pastas do PC.

Variáveis de ambiente úteis (principalmente nos testes):
- ``ROTINAS_CONFIG_DIR``: pasta alternativa com os ``*.json`` de configuração.
- ``ROTINAS_ENV``: caminho alternativo do ``.env``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

_cache: dict[tuple[str, str], dict] = {}


class ErroConfig(Exception):
    """Configuração ausente ou inválida."""


def dir_config() -> Path:
    return Path(os.environ.get("ROTINAS_CONFIG_DIR") or (RAIZ / "config"))


def carregar(nome: str) -> dict:
    """Lê ``config/<nome>.json`` (com cache por pasta até ``limpar_cache``)."""
    pasta = dir_config()
    chave = (str(pasta), nome)
    if chave not in _cache:
        caminho = pasta / f"{nome}.json"
        if not caminho.exists():
            raise ErroConfig(f"Arquivo de configuração não encontrado: {caminho}")
        try:
            _cache[chave] = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ErroConfig(f"JSON inválido em {caminho}: {e}") from e
    return _cache[chave]


def limpar_cache() -> None:
    """Esquece os JSON lidos: o próximo ``carregar`` relê do disco (o vigia chama a cada pedido)."""
    _cache.clear()


def expandir(caminho: str | os.PathLike) -> Path:
    """Expande ``%VAR%`` (estilo Windows), ``$VAR`` e ``~`` em qualquer sistema."""
    texto = str(caminho)
    texto = re.sub(r"%([A-Za-z0-9_]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), texto)
    texto = os.path.expandvars(texto)
    return Path(os.path.expanduser(texto))


@dataclass(frozen=True)
class Pastas:
    stories_fonte: Path
    rotinas: Path
    sistema: Path
    capcut_rascunhos: Path
    capcut_apps: Path
    videos: Path

    @property
    def fila(self) -> Path:
        return self.rotinas / "fila"

    @property
    def logs(self) -> Path:
        return self.rotinas / "logs"

    @property
    def registros(self) -> Path:
        return self.rotinas / "registros"

    @property
    def trabalho_stories(self) -> Path:
        return self.rotinas / "stories"

    @property
    def backups(self) -> Path:
        return self.rotinas / "backups"

    def pasta_do_dia(self, data: str) -> Path:
        return self.stories_fonte / data


def pastas() -> Pastas:
    d = carregar("pastas")
    campos = ["stories_fonte", "rotinas", "sistema", "capcut_rascunhos", "capcut_apps", "videos"]
    faltando = [c for c in campos if not d.get(c)]
    if faltando:
        raise ErroConfig(f"config/pastas.json sem: {', '.join(faltando)}")
    return Pastas(**{c: expandir(d[c]) for c in campos})


# ---------------------------------------------------------------- .env

def caminho_env() -> Path:
    return Path(os.environ.get("ROTINAS_ENV") or (RAIZ / ".env"))


def ler_env(caminho: Path | None = None) -> dict[str, str]:
    """Lê o ``.env`` (KEY=VALOR, comentários com #). Não loga nada."""
    caminho = caminho or caminho_env()
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[chave.strip()] = valor
    return valores


def segredo(nome: str) -> str | None:
    """Valor de uma variável do ``.env`` (o ambiente do processo tem prioridade)."""
    valor = os.environ.get(nome)
    if valor:
        return valor
    return ler_env().get(nome) or None


def valores_secretos() -> list[str]:
    """Valores que nunca podem aparecer em log, relatório ou execução enviada ao git."""
    nomes = set(ler_env().keys())
    nomes |= {n for n in os.environ if n.startswith(("SUPABASE_", "ROTINAS_SEGREDO_", "OPENAI_"))}
    valores = []
    for n in nomes:
        v = os.environ.get(n) or ler_env().get(n)
        if v and len(v) >= 6:
            valores.append(v)
    return sorted(set(valores), key=len, reverse=True)
