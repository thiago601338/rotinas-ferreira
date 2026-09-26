"""Utilitários do rascunho do CapCut: tempo em µs, ids, JSON do rascunho, criptografia, app aberto e backup.

O formato é o do CapCut internacional (``draft_info.json``/``draft_content.json``/``template-2.tmp``
+ ``draft_meta_info.json`` na pasta do projeto, ``root_meta_info.json`` na raiz dos rascunhos).
Detalhes e fontes em ``conhecimento/capcut-avaliacao-ferramentas.md``.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from .. import config, ferramentas, registro

log = registro.obter("video.capcut")

US_POR_S = 1_000_000


class ErroCapCut(RuntimeError):
    """Problema com o CapCut ou com um rascunho."""


class CapCutAberto(ErroCapCut):
    """O CapCut está aberto: gravar agora seria sobrescrito pelo salvamento automático dele."""


class GabaritoCriptografado(ErroCapCut):
    """O arquivo do rascunho não é JSON aberto (versão que criptografa)."""


def cfg() -> dict:
    return config.carregar("capcut")


# ---------------------------------------------------------------- tempo, ids, números

def us(segundos: float) -> int:
    """Segundos → microssegundos inteiros (arredondado)."""
    return int(round(float(segundos) * US_POR_S))


def segundos(microssegundos: int) -> float:
    return microssegundos / US_POR_S


def novo_id(maiusculo: bool | None = None) -> str:
    """UUID com hífens; maiúsculo como o CapCut grava (config ``ids_maiusculos``)."""
    if maiusculo is None:
        maiusculo = bool(cfg().get("ids_maiusculos", True))
    texto = str(uuid.uuid4())
    return texto.upper() if maiusculo else texto


def db_para_linear(db: float) -> float:
    """Ganho em dB → volume linear do CapCut (0 dB = 1,0; −6 dB ≈ 0,5)."""
    return round(10 ** (float(db) / 20.0), 6)


def linear_para_db(linear: float) -> float:
    import math

    return float("-inf") if linear <= 0 else 20 * math.log10(linear)


def tamanho_utf16(texto: str) -> int:
    """Comprimento em unidades UTF-16 (é o que o CapCut usa em ``styles[].range``)."""
    return len(texto.encode("utf-16-le")) // 2


def cor_rgb(hexa: str) -> list[float]:
    """``"#F7C204"`` → ``[0.968, 0.76, 0.015]`` (0–1, como no conteúdo do texto)."""
    h = hexa.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        raise ValueError(f"Cor inválida: {hexa!r} (use #RRGGBB)")
    return [round(int(h[i:i + 2], 16) / 255, 6) for i in (0, 2, 4)]


def carimbo_como(referencia, agora: datetime | None = None):
    """Data/hora atual na mesma unidade do valor de referência do gabarito (s, ms ou µs).

    Referência 0, vazia ou não numérica → devolve a própria referência (não inventa campo).
    """
    if isinstance(referencia, bool) or not isinstance(referencia, (int, float)) or referencia <= 0:
        return referencia
    t = (agora or datetime.now()).timestamp()
    if referencia >= 1e14:
        return int(t * US_POR_S)
    if referencia >= 1e11:
        return int(t * 1000)
    return int(t)


# ---------------------------------------------------------------- caminhos

def estilo_separador(*exemplos: str | None) -> str:
    """``"/"`` ou ``"\\\\"`` conforme os caminhos do gabarito (config ``separador_caminho``)."""
    escolha = cfg().get("separador_caminho", "auto")
    if escolha in ("/", "\\"):
        return escolha
    for ex in exemplos:
        if isinstance(ex, str) and re.match(r"^[A-Za-z]:[\\/]", ex):
            return "\\" if ("\\" in ex and "/" not in ex) else "/"
    return "/"


def caminho_capcut(caminho: str | os.PathLike, separador: str = "/") -> str:
    """Caminho absoluto no estilo que o CapCut grava (``C:/Users/...`` por padrão)."""
    texto = str(caminho)
    if separador == "/":
        return texto.replace("\\", "/")
    return texto.replace("/", "\\")


def sanitizar_nome(nome: str) -> str:
    """Nome de projeto válido no Windows (sem ``<>:"/\\|?*``, sem ponto/espaço no fim)."""
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", nome).strip().rstrip(". ")
    return limpo or "Rascunho"


# ---------------------------------------------------------------- JSON do rascunho

def ler_json(caminho: Path):
    return json.loads(Path(caminho).read_text(encoding="utf-8-sig"))


def gravar_json(caminho: Path, dados, recuo: int | str | None = None) -> None:
    """Grava de forma atômica (temporário + troca). Sem recuo = compacto, como o CapCut."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if recuo in (None, 0, ""):
        texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    else:
        texto = json.dumps(dados, ensure_ascii=False, indent=recuo)
    tmp = caminho.with_name(caminho.name + ".tmp-rotinas")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, caminho)


def recuo_de(texto: str) -> int | str | None:
    """Recuo usado num JSON existente (para regravar no mesmo estilo)."""
    m = re.search(r"\n([ \t]+)\S", texto)
    if not m:
        return None
    return "\t" if "\t" in m.group(1) else len(m.group(1))


def formato(caminho: Path) -> str:
    """``"ausente"``, ``"vazio"``, ``"json"``, ``"json_invalido"`` ou ``"criptografado"``."""
    caminho = Path(caminho)
    if not caminho.is_file():
        return "ausente"
    with open(caminho, "rb") as f:
        inicio = f.read(4096)
    limpo = inicio.lstrip(b"\xef\xbb\xbf").lstrip()
    if not limpo:
        return "vazio"
    if not limpo.startswith(b"{"):
        return "criptografado"
    try:
        ler_json(caminho)
    except ValueError:
        return "json_invalido"
    return "json"


def criptografado(caminho: Path) -> bool:
    """Teste rápido do conhecimento: arquivo que não começa com ``{`` não é JSON aberto."""
    return formato(caminho) == "criptografado"


def eh_linha_do_tempo(valor) -> bool:
    return isinstance(valor, dict) and isinstance(valor.get("tracks"), list) and isinstance(valor.get("materials"), dict)


def achar_linha_do_tempo(valor, caminho: tuple = (), profundidade: int = 0):
    """Acha a linha do tempo no JSON, direta ou dentro de um envelope (objeto ou texto JSON).

    Devolve ``(documento, caminho)`` — o caminho é uma tupla de chaves; ``"chave:json"`` marca um
    campo de texto que contém JSON — ou ``None``.
    """
    if eh_linha_do_tempo(valor):
        return valor, caminho
    if profundidade >= 3 or not isinstance(valor, dict):
        return None
    preferidas = ["draft_content", "draft_info", "timeline", "content", "data", "draft"]
    for chave in sorted(valor, key=lambda k: preferidas.index(k) if k in preferidas else 99):
        filho = valor[chave]
        if isinstance(filho, str) and filho.lstrip().startswith("{"):
            try:
                achado = achar_linha_do_tempo(json.loads(filho), caminho + (f"{chave}:json",), profundidade + 1)
            except ValueError:
                achado = None
        elif isinstance(filho, dict):
            achado = achar_linha_do_tempo(filho, caminho + (chave,), profundidade + 1)
        else:
            achado = None
        if achado:
            return achado
    return None


def recolocar(raiz, caminho: tuple, documento):
    """Põe ``documento`` no lugar indicado por ``caminho`` (o inverso de ``achar_linha_do_tempo``)."""
    if not caminho:
        return documento
    chave, resto = caminho[0], caminho[1:]
    if chave.endswith(":json"):
        chave = chave[: -len(":json")]
        interno = recolocar(json.loads(raiz[chave]), resto, documento)
        raiz[chave] = json.dumps(interno, ensure_ascii=False, separators=(",", ":"))
    else:
        raiz[chave] = recolocar(raiz[chave], resto, documento)
    return raiz


# ---------------------------------------------------------------- CapCut aberto

def _processos_windows() -> str:
    r = ferramentas.rodar(["tasklist", "/FO", "CSV", "/NH"], timeout=20, verificar=False)
    if r.returncode != 0 or not (r.stdout or "").strip():
        # Sem a lista de processos não dá para garantir que o CapCut está fechado: recusa em vez de arriscar.
        raise ErroCapCut("Não consegui listar os processos (tasklist) para conferir se o CapCut está fechado.")
    return r.stdout


def capcut_aberto() -> bool:
    """O CapCut está rodando? (Windows: ``tasklist``; fora do Windows devolve ``False``.)

    Compara o nome exato da imagem, linha por linha, para não confundir com outro processo.
    """
    if not sys.platform.startswith("win"):
        return False
    alvo = str(cfg().get("processo", "CapCut.exe")).lower()
    for linha in _processos_windows().splitlines():
        primeiro = linha.split(",", 1)[0].strip().strip('"').lower()
        if primeiro == alvo:
            return True
    return False


def exigir_capcut_fechado() -> None:
    if capcut_aberto():
        raise CapCutAberto(
            "O CapCut está aberto. Feche o CapCut (inclusive na bandeja do sistema) e rode de novo: "
            "com ele aberto, o salvamento automático sobrescreve o rascunho."
        )


# ---------------------------------------------------------------- cópia e backup

def ignorar(nome: str, padroes: list[str]) -> bool:
    return any(fnmatch.fnmatch(nome, p) for p in padroes)


def copiar_arvore(origem: Path, destino: Path, max_bytes: int | None = None,
                  ignorar_padroes: list[str] | None = None, extensoes_fora: set[str] | None = None) -> dict:
    """Copia arquivos de ``origem`` para ``destino`` (cria pastas). Nunca apaga nada no destino."""
    copiados: list[str] = []
    omitidos: list[dict] = []
    padroes = ignorar_padroes or []
    for pasta_atual, subpastas, arquivos in os.walk(origem):
        subpastas[:] = sorted(s for s in subpastas if not ignorar(s, padroes))
        atual = Path(pasta_atual)
        for nome in sorted(arquivos):
            arq = atual / nome
            rel = arq.relative_to(origem)
            if ignorar(nome, padroes):
                omitidos.append({"arquivo": rel.as_posix(), "motivo": "ignorado"})
                continue
            if extensoes_fora and arq.suffix.lower() in extensoes_fora:
                omitidos.append({"arquivo": rel.as_posix(), "motivo": "mídia"})
                continue
            try:
                tamanho = arq.stat().st_size
            except OSError as e:
                omitidos.append({"arquivo": rel.as_posix(), "motivo": str(e)})
                continue
            if max_bytes is not None and tamanho > max_bytes:
                omitidos.append({"arquivo": rel.as_posix(), "motivo": f"grande ({tamanho // (1024 * 1024)} MB)"})
                continue
            alvo = destino / rel
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arq, alvo)
            copiados.append(rel.as_posix())
    return {"copiados": copiados, "omitidos": omitidos}


def backup(pasta_rascunhos: Path, projetos: list[Path] | None = None, base: Path | None = None) -> Path:
    """Copia os arquivos soltos da raiz dos rascunhos (``root_meta_info.json``…) e os projetos indicados.

    Destino: ``<rotinas>/backups/capcut/<aaaa-mm-dd_hhmmss>/``. Nunca apaga nada.
    """
    pasta_rascunhos = Path(pasta_rascunhos)
    base = Path(base) if base else config.pastas().backups / "capcut"
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino, n = base / carimbo, 2
    while destino.exists():
        destino, n = base / f"{carimbo}-{n}", n + 1
    destino.mkdir(parents=True)
    limite = int(float(cfg().get("backup_max_mb_por_arquivo", 200)) * 1024 * 1024)
    manifesto: dict = {"pasta_rascunhos": str(pasta_rascunhos), "criado_em": datetime.now().isoformat(timespec="seconds"),
                       "raiz": [], "projetos": {}}
    if pasta_rascunhos.is_dir():
        for arq in sorted(pasta_rascunhos.iterdir()):
            if arq.is_file():
                shutil.copy2(arq, destino / arq.name)
                manifesto["raiz"].append(arq.name)
    for projeto in projetos or []:
        projeto = Path(projeto)
        if projeto.is_dir():
            manifesto["projetos"][projeto.name] = copiar_arvore(projeto, destino / "projetos" / projeto.name, limite)
    gravar_json(destino / "manifesto.json", manifesto, recuo=2)
    log.info("Backup dos rascunhos do CapCut em %s", destino)
    return destino


# ---------------------------------------------------------------- índice (root_meta_info.json)

def chave_do_indice(indice: dict) -> str | None:
    """Nome da lista de projetos no ``root_meta_info.json`` (normalmente ``all_draft_store``)."""
    for chave, valor in indice.items():
        if isinstance(valor, list) and any(isinstance(e, dict) and ("draft_fold_path" in e or "draft_id" in e) for e in valor):
            return chave
    for chave, valor in indice.items():
        if isinstance(valor, list) and re.search(r"draft_store", chave, re.I):
            return chave
    return None


def ler_indice(pasta_rascunhos: Path) -> dict | None:
    arq = Path(pasta_rascunhos) / cfg().get("arquivo_indice", "root_meta_info.json")
    if formato(arq) != "json":
        return None
    dados = ler_json(arq)
    return dados if isinstance(dados, dict) else None


def nomes_no_indice(indice: dict | None) -> set[str]:
    if not indice:
        return set()
    chave = chave_do_indice(indice)
    if not chave:
        return set()
    return {str(e.get("draft_name")) for e in indice.get(chave, []) if isinstance(e, dict) and e.get("draft_name")}


def nome_livre(pasta_rascunhos: Path, nome: str, indice: dict | None = None) -> str:
    """``nome``, ou ``nome (2)``, ``nome (3)``… se já existir pasta ou projeto com esse nome."""
    nome = sanitizar_nome(nome)
    usados = {n.lower() for n in nomes_no_indice(indice)}
    candidato, n = nome, 2
    while (Path(pasta_rascunhos) / candidato).exists() or candidato.lower() in usados:
        candidato, n = f"{nome} ({n})", n + 1
    return candidato
