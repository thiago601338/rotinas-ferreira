"""Localiza programas externos (ffmpeg, ffprobe, adb, git) e roda comandos."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

NO_WINDOWS = sys.platform.startswith("win")


class FerramentaAusente(RuntimeError):
    """Programa externo não encontrado."""


class ErroComando(RuntimeError):
    """Comando externo terminou com erro."""

    def __init__(self, mensagem: str, retorno: int | None = None, saida: str = "", erro: str = ""):
        super().__init__(mensagem)
        self.retorno = retorno
        self.saida = saida
        self.erro = erro


def _candidatos_padrao(nome: str) -> list[str]:
    exe = nome + (".exe" if NO_WINDOWS else "")
    local = os.environ.get("LOCALAPPDATA", "")
    cands: list[str] = []
    if local:
        cands.append(os.path.join(local, "Microsoft", "WinGet", "Links", exe))
        cands += sorted(glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*", "**", exe), recursive=True))
    if nome in ("ffmpeg", "ffprobe"):
        cands += [os.path.join("C:\\ffmpeg", "bin", exe), os.path.join("C:\\Program Files", "ffmpeg", "bin", exe)]
    if nome == "git":
        cands += [r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe"]
    if nome == "adb":
        if local:
            cands.append(os.path.join(local, "Android", "Sdk", "platform-tools", exe))
        cands.append(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
    return cands


def localizar(nome: str, candidatos: list[str] | None = None) -> str | None:
    """Caminho do executável ou ``None``.

    Ordem: variável ``ROTINAS_<NOME>``, ``candidatos`` (da config), PATH, locais conhecidos do Windows.
    """
    var = os.environ.get(f"ROTINAS_{nome.upper()}")
    if var and Path(var).exists():
        return var
    for c in candidatos or []:
        c = str(config.expandir(c))
        if os.sep in c or "/" in c:
            if Path(c).is_file():
                return c
        else:
            achado = shutil.which(c)
            if achado:
                return achado
    achado = shutil.which(nome)
    if achado:
        return achado
    for c in _candidatos_padrao(nome):
        if Path(c).is_file():
            return c
    return None


def exigir(nome: str, candidatos: list[str] | None = None) -> str:
    caminho = localizar(nome, candidatos)
    if not caminho:
        raise FerramentaAusente(
            f"Não encontrei o programa '{nome}'. Rode o instalar.bat de novo ou confira o PATH."
        )
    return caminho


def rodar(
    cmd: list[str],
    timeout: float | None = None,
    verificar: bool = True,
    entrada: str | None = None,
    binario: bool = False,
    cwd: str | os.PathLike | None = None,
) -> subprocess.CompletedProcess:
    """Roda um comando sem abrir janela (no Windows) e com saída em UTF-8."""
    opcoes: dict = {}
    if NO_WINDOWS:
        opcoes["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(
            [str(c) for c in cmd],
            input=entrada,
            capture_output=True,
            timeout=timeout,
            text=not binario,
            encoding=None if binario else "utf-8",
            errors=None if binario else "replace",
            cwd=cwd,
            **opcoes,
        )
    except FileNotFoundError as e:
        raise FerramentaAusente(f"Programa não encontrado: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ErroComando(f"Tempo esgotado ({timeout} s) em: {Path(str(cmd[0])).name}") from e
    if verificar and r.returncode != 0:
        erro = r.stderr if not binario else r.stderr.decode("utf-8", "replace")
        raise ErroComando(
            f"{Path(str(cmd[0])).name} terminou com código {r.returncode}: {erro.strip()[-800:]}",
            r.returncode,
            r.stdout if not binario else "",
            erro,
        )
    return r


def versao(nome: str, argumento: str = "-version") -> str | None:
    """Primeira linha da versão de um programa, ou ``None``."""
    caminho = localizar(nome)
    if not caminho:
        return None
    try:
        r = rodar([caminho, argumento], timeout=20, verificar=False)
    except Exception:
        return None
    texto = (r.stdout or r.stderr or "").strip().splitlines()
    return texto[0] if texto else None
