"""A1 — prepara a pasta do dia dos stories.

- Mídia nova (nome fora do padrão ``<LETRA> - <n>.<ext>``) ganha a próxima letra livre:
  vídeos primeiro (``B - 1.mp4``), depois as fotos (``B - 2.jpg``…), cada grupo na ordem de captura.
- ``.mov``/``.m4v``/``.3gp`` viram ``.mp4`` e HEIC vira ``.jpg``, sempre em arquivo novo. O original
  vai para ``_originais`` (nunca apaga, nunca sobrescreve). ``_originais/renomeados.json`` guarda de
  onde veio cada arquivo: é o que deixa rodar de novo sem duplicar nada e retomar uma rodada interrompida.
- Detecta vídeo sem áudio ou em silêncio (recebe música do Instagram).
- Gera uma folha de contato por letra e grava ``manifesto.json`` na pasta de trabalho.

Regras em ``conhecimento/stories.md``.
"""

from __future__ import annotations

import argparse
import errno
import functools
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, ferramentas, folha, midia, registro

log = registro.obter("stories.pasta")

PADRAO_NOME = re.compile(r"^(?P<letra>[A-Z]{1,2}) - (?P<n>\d+)\.(?P<ext>[A-Za-z0-9]+)$")
# "b - 1.jpg": no Windows é o mesmo arquivo que "B - 1.jpg"; não pode virar mídia nova nem ter a letra reaproveitada.
PADRAO_NOME_MINUSCULA = re.compile(PADRAO_NOME.pattern, re.IGNORECASE)
PADRAO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PADRAO_FOLHA = re.compile(r"^[A-Z]{1,2}$")
# Quando há dois arquivos com o mesmo número (ex.: "A - 1.mov" e "A - 1.mp4"), vale o primeiro desta lista.
PREFERENCIA_EXT = [".mp4", ".jpg", ".jpeg", ".png", ".webp"]
MANIFESTO = "manifesto.json"
MANIFESTO_SIMULADO = "manifesto-simulado.json"


class ErroPasta(RuntimeError):
    """Problema ao preparar a pasta do dia (mensagem pronta para o usuário)."""

    def __init__(self, mensagem: str, resultado_parcial: dict | None = None):
        super().__init__(mensagem)
        if resultado_parcial is not None:
            self.resultado_parcial = resultado_parcial


# ---------------------------------------------------------------- configuração

def _cfg() -> dict:
    """Chaves de ``config/stories.json`` usadas aqui (erro claro se faltar alguma)."""
    d = config.carregar("stories")
    faltando = [c for c in ("agrupamento_intervalo_min", "pasta_originais", "max_midias_por_letra", "preparar") if c not in d]
    if faltando:
        raise config.ErroConfig(f"config/stories.json sem: {', '.join(faltando)}")
    p = d["preparar"]
    faltando = [c for c in ("registro_renomeacoes", "converter_para_mp4", "converter_para_jpg", "jpg_qualidade", "folha") if c not in p]
    if faltando:
        raise config.ErroConfig(f"config/stories.json → preparar sem: {', '.join(faltando)}")
    return {
        "intervalo_min": float(d["agrupamento_intervalo_min"]),
        "originais": str(d["pasta_originais"]),
        "max_midias": int(d["max_midias_por_letra"]),
        "registro": str(p["registro_renomeacoes"]),
        "para_mp4": {e.lower() for e in p["converter_para_mp4"]},
        "para_jpg": {e.lower() for e in p["converter_para_jpg"]},
        "jpg_qualidade": int(p["jpg_qualidade"]),
        "folha": dict(p["folha"]),
    }


def _registrar_heif() -> None:
    """Deixa o Pillow ler HEIC (inclusive a data do EXIF) se o pillow-heif estiver instalado."""
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
    except ImportError:
        pass


# ---------------------------------------------------------------- letras

def indice_letra(letra: str) -> int:
    """``A`` → 0, ``Z`` → 25, ``AA`` → 26, ``AB`` → 27…"""
    n = 0
    for c in letra:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def letra_do_indice(indice: int) -> str:
    """Inverso de ``indice_letra`` (até ``ZZ``, o limite do padrão de nome)."""
    if not 0 <= indice <= 701:
        raise ErroPasta("Acabaram as letras (o máximo é ZZ). Divida as mídias em outra pasta de data.")
    n, letras = indice + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


# ---------------------------------------------------------------- estruturas

@dataclass
class Midia:
    """Uma mídia de uma letra: pronta na pasta ou a criar (``operacao``) a partir do original."""

    letra: str
    arquivo: str  # nome final, com extensão
    tipo: str  # "video" | "foto"
    fonte: Path  # arquivo a descrever: o final, ou o original enquanto o final não existe
    origem: str | None = None  # caminho do original relativo à pasta do dia (com "/")
    operacao: str | None = None  # "mp4" | "jpg" | "copia" | None (já pronta)
    convertido: str | None = None
    capturado_em: datetime | None = None

    @property
    def nome(self) -> str:
        return Path(self.arquivo).stem


@dataclass
class Letra:
    letra: str
    nova: bool
    midias: list[Midia]


@dataclass
class Candidata:
    """Mídia nova encontrada na pasta (ainda com o nome original)."""

    caminho: Path
    rel: str
    subpasta: str | None
    tipo: str
    capturado_em: datetime


def _rel(caminho: Path, pasta: Path) -> str:
    return caminho.relative_to(pasta).as_posix()


def _eh_midia(caminho: Path) -> bool:
    return midia.eh_foto(caminho) or midia.eh_video(caminho)


def _ignorar(nome: str) -> bool:
    """Ocultos, temporários do Office e arquivos parciais desta rotina."""
    return nome.startswith((".", "~$")) or ".parcial." in nome


# ---------------------------------------------------------------- registro de renomeações

class Registro:
    """``<pasta do dia>/_originais/renomeados.json``: origem → arquivo final de cada mídia renomeada.

    Estados de uma entrada: ``pendente`` (vai criar o final), ``criado`` (final pronto, original ainda
    na pasta), ``feito`` (original guardado em ``_originais``).
    """

    def __init__(self, pasta: Path, cfg: dict):
        self.caminho = pasta / cfg["originais"] / cfg["registro"]
        self.entradas: list[dict] = []
        self._gravado = ""
        if self.caminho.exists():
            try:
                texto = self.caminho.read_text(encoding="utf-8-sig")
                self.entradas = list(json.loads(texto)["entradas"])
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise ErroPasta(f"Não consegui ler {self.caminho} ({e}). Tire esse arquivo da pasta e rode de novo.") from e
            self._gravado = self._texto()

    def _texto(self) -> str:
        return json.dumps(
            {"_comentario": "Gerado por stories-preparar. De onde veio cada arquivo da pasta do dia. Não editar.",
             "entradas": self.entradas},
            ensure_ascii=False, indent=2,
        )

    def gravar(self) -> None:
        texto = self._texto()
        if texto == self._gravado or (not self.entradas and not self.caminho.exists()):
            return
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_name(self.caminho.name + ".tmp")
        tmp.write_text(texto, encoding="utf-8")
        os.replace(tmp, self.caminho)
        self._gravado = texto

    def pendentes(self) -> list[dict]:
        return [e for e in self.entradas if e.get("estado") != "feito"]

    def do_arquivo(self, arquivo: str) -> dict | None:
        achadas = [e for e in self.entradas if e.get("arquivo") == arquivo]
        return achadas[-1] if achadas else None

    def da_origem(self, rel: str) -> dict | None:
        achadas = [e for e in self.entradas if e.get("origem") == rel]
        return achadas[-1] if achadas else None

    def remover(self, entradas: list[dict]) -> None:
        ids = {id(e) for e in entradas}
        self.entradas = [e for e in self.entradas if id(e) not in ids]


def _mesmo_original(caminho: Path, entrada: dict) -> bool:
    try:
        tamanho = caminho.stat().st_size
    except OSError:
        return False
    return tamanho == entrada.get("tamanho_origem") and midia.hash_arquivo(caminho) == entrada.get("hash_origem")


# ---------------------------------------------------------------- operações em arquivo (nunca sobrescrevem)

def _temporario(destino: Path) -> Path:
    tmp = destino.with_name(f"{destino.stem}.parcial{destino.suffix}")
    if tmp.exists():
        tmp.unlink()  # sobra nossa de uma tentativa anterior
    return tmp


def _remover_nosso(caminho: Path) -> None:
    """Apaga um arquivo criado por esta rotina nesta rodada (nunca mídia do usuário)."""
    try:
        try:
            caminho.unlink(missing_ok=True)
        except PermissionError:
            # no Windows, arquivo somente leitura não apaga; shutil.copy2 copia esse atributo do original
            os.chmod(caminho, stat.S_IWRITE | stat.S_IREAD)
            caminho.unlink(missing_ok=True)
    except OSError as e:
        log.warning("Não consegui apagar o arquivo temporário %s: %s", caminho, e)


def _ja_existe(destino: Path) -> FileExistsError:
    return FileExistsError(errno.EEXIST, "já existe", str(destino))


def _publicar(tmp: Path, destino: Path) -> None:
    """Dá ao temporário o nome final sem nunca sobrescrever (``FileExistsError`` se o destino existir)."""
    if os.name == "nt":
        os.rename(tmp, destino)  # no Windows, rename falha se o destino existir
        return
    try:
        os.link(tmp, destino)  # falha se o destino existir
    except FileExistsError:
        raise
    except OSError:
        if os.path.lexists(destino):
            raise _ja_existe(destino)
        os.rename(tmp, destino)
        return
    tmp.unlink()


def _renomear_sem_sobrescrever(origem: Path, destino: Path) -> None:
    if os.name != "nt" and os.path.lexists(destino):
        raise _ja_existe(destino)
    os.rename(origem, destino)


def _nome_livre(destino: Path) -> Path:
    """``IMG_1.jpg`` → ``IMG_1 (2).jpg`` → ``IMG_1 (3).jpg``… até achar um nome que não existe."""
    candidato, k = destino, 1
    while os.path.lexists(candidato):
        k += 1
        candidato = destino.with_name(f"{destino.stem} ({k}){destino.suffix}")
    return candidato


def _copiar(origem: Path, destino: Path) -> None:
    tmp = _temporario(destino)
    try:
        shutil.copy2(origem, tmp)
        _publicar(tmp, destino)
    except BaseException:
        _remover_nosso(tmp)
        raise


def _foto_para_jpg(origem: Path, destino: Path, qualidade: int) -> None:
    """HEIC → JPEG (arquivo novo), já na orientação certa, com EXIF e perfil de cor quando houver."""
    img = midia.abrir_imagem(origem)
    try:
        # getexif() relê o bloco venha ele com ou sem o cabeçalho "Exif\0\0" (o pillow-heif varia entre
        # versões); tobytes() devolve sempre no formato que o JPEG espera. A orientação já foi aplicada.
        dados_exif = img.getexif()
        dados_exif.pop(0x0112, None)
        exif = dados_exif.tobytes() if len(dados_exif) else None
        icc = img.info.get("icc_profile")
        rgb = img.convert("RGB")
    finally:
        img.close()
    opcoes: dict = {"quality": qualidade}
    if exif:
        opcoes["exif"] = exif
    if icc:
        opcoes["icc_profile"] = icc
    tmp = _temporario(destino)
    try:
        rgb.save(tmp, "JPEG", **opcoes)
        _publicar(tmp, destino)
    except BaseException:
        _remover_nosso(tmp)
        raise


def _criar_final(origem: Path, destino: Path, operacao: str, cfg: dict) -> str | None:
    """Cria o arquivo final a partir do original. Devolve o modo de conversão (ou ``None`` se for cópia)."""
    if os.path.lexists(destino):
        raise _ja_existe(destino)
    if operacao == "mp4":
        try:
            modo = midia.converter_para_mp4(origem, destino)["modo"]
        except BaseException:
            _remover_nosso(destino.with_name(f"{destino.stem}.parcial{destino.suffix}"))
            raise
    elif operacao == "jpg":
        _foto_para_jpg(origem, destino, cfg["jpg_qualidade"])
        modo = "recodificado"
    elif operacao == "copia":
        _copiar(origem, destino)
        modo = None
    else:  # pragma: no cover - erro de programação
        raise ValueError(f"operação desconhecida: {operacao}")
    try:
        st = origem.stat()
        os.utime(destino, (st.st_atime, st.st_mtime))  # a data do arquivo acompanha a do original
    except OSError:
        pass
    return modo


def _operacao(caminho: Path, cfg: dict) -> tuple[str, str]:
    """(operação, extensão final) para uma mídia nova."""
    ext = caminho.suffix.lower()
    if ext in cfg["para_mp4"]:
        return "mp4", ".mp4"
    if ext in cfg["para_jpg"]:
        return "jpg", ".jpg"
    return "copia", ext


# ---------------------------------------------------------------- varredura

def _varrer(pasta: Path) -> tuple[dict[str, dict[int, list[Path]]], list[tuple[Path, str | None]], list[str], set[str]]:
    """(letras existentes na raiz, mídias com nome fora do padrão, avisos, letras escritas em minúscula)."""
    existentes: dict[str, dict[int, list[Path]]] = {}
    soltas: list[tuple[Path, str | None]] = []
    avisos: list[str] = []
    minusculas: set[str] = set()
    for item in sorted(pasta.iterdir()):
        if _ignorar(item.name):
            continue
        if item.is_dir():
            if item.name.startswith("_"):
                continue
            for arq in sorted(item.rglob("*")):
                partes = arq.relative_to(pasta).parts
                if any(p.startswith(("_", ".")) for p in partes[:-1]):
                    continue
                if not arq.is_file() or _ignorar(arq.name) or not _eh_midia(arq):
                    continue
                if PADRAO_NOME.match(arq.name):
                    avisos.append(f"{_rel(arq, pasta)} tem nome de letra mas está numa subpasta: ignorado "
                                  "(as letras ficam na raiz da pasta do dia)")
                    continue
                soltas.append((arq, item.name))
        elif item.is_file() and _eh_midia(item):
            m = PADRAO_NOME.match(item.name)
            mm = None if m else PADRAO_NOME_MINUSCULA.match(item.name)
            if m:
                existentes.setdefault(m["letra"], {}).setdefault(int(m["n"]), []).append(item)
            elif mm:
                letra = mm["letra"].upper()
                minusculas.add(letra)
                avisos.append(f"{item.name} ignorado: letra em minúscula. Renomeie para "
                              f"\"{letra} - {int(mm['n'])}{Path(item.name).suffix}\" e rode de novo")
            else:
                soltas.append((item, None))
    return existentes, soltas, avisos, minusculas


def _filtrar_registradas(soltas, pasta: Path, reg: Registro, cfg: dict, avisos: list[str]):
    """Tira das mídias novas os originais que já viraram um arquivo final (rodada anterior)."""
    novas = []
    for arq, sub in soltas:
        rel = _rel(arq, pasta)
        e = reg.da_origem(rel)
        if e and (pasta / e["arquivo"]).exists() and _mesmo_original(arq, e):
            if e.get("estado") == "feito":
                avisos.append(f"{rel} já tinha virado {e['arquivo']}: ignorado "
                              f"(para usar de novo numa letra nova, tire {e['arquivo']} da pasta)")
            else:
                avisos.append(f"{rel} já virou {e['arquivo']}, mas o original ainda não foi para {cfg['originais']}: "
                              "rode de novo (sem simular) para concluir")
            continue
        novas.append((arq, sub))
    return novas


def _candidata(arq: Path, sub: str | None, pasta: Path) -> Candidata:
    tipo = "video" if midia.eh_video(arq) else "foto"
    return Candidata(arq, _rel(arq, pasta), sub, tipo, midia.data_captura(arq))


def _escolher(arquivos: list[Path]) -> tuple[Path, list[Path]]:
    def chave(p: Path):
        ext = p.suffix.lower()
        return (PREFERENCIA_EXT.index(ext) if ext in PREFERENCIA_EXT else len(PREFERENCIA_EXT), p.name)

    ordenados = sorted(arquivos, key=chave)
    return ordenados[0], ordenados[1:]


def _data_registrada(entrada: dict | None) -> datetime | None:
    try:
        return datetime.fromisoformat(entrada["capturado_em"]) if entrada and entrada.get("capturado_em") else None
    except ValueError:
        return None


def _letras_existentes(existentes, pasta: Path, reg: Registro, retomadas: set[str], cfg: dict, avisos: list[str]) -> list[Letra]:
    letras = []
    for letra in sorted(existentes, key=indice_letra):
        midias = []
        for n in sorted(existentes[letra]):
            escolhido, extras = _escolher(existentes[letra][n])
            for x in extras:
                avisos.append(f"{x.name} ignorado: já existe {escolhido.name} com o mesmo número")
            tipo = "video" if midia.eh_video(escolhido) else "foto"
            ext = escolhido.suffix.lower()
            if ext in cfg["para_mp4"] or ext in cfg["para_jpg"]:
                # letra antiga com .mov/HEIC: vira .mp4/.jpg e o original vai para _originais
                operacao, ext_final = ("mp4", ".mp4") if ext in cfg["para_mp4"] else ("jpg", ".jpg")
                midias.append(Midia(letra, f"{escolhido.stem}{ext_final}", tipo, escolhido, escolhido.name,
                                    operacao, capturado_em=midia.data_captura(escolhido)))
                continue
            e = reg.do_arquivo(escolhido.name)
            capturado = _data_registrada(e) or midia.data_captura(escolhido)
            midias.append(Midia(letra, escolhido.name, tipo, escolhido, e.get("origem") if e else None,
                                None, e.get("convertido") if e else None, capturado))
        letras.append(Letra(letra, letra in retomadas, midias))
    return letras


# ---------------------------------------------------------------- agrupamento

def _ordenar_dentro(grupo: list[Candidata]) -> list[Candidata]:
    """Vídeos primeiro, depois fotos, cada um na ordem de captura."""
    return sorted(grupo, key=lambda c: (c.tipo != "video", c.capturado_em, c.rel))


def agrupar(candidatas: list[Candidata], intervalo_min: float) -> list[list[Candidata]]:
    """Heurística: cada subpasta é uma letra; na raiz, letra nova quando o intervalo entre capturas
    passa de ``intervalo_min`` ou quando aparece um vídeo depois de uma foto."""
    por_sub: dict[str, list[Candidata]] = {}
    soltas: list[Candidata] = []
    for c in candidatas:
        (por_sub.setdefault(c.subpasta, []) if c.subpasta else soltas).append(c)
    grupos = list(por_sub.values())
    atual: list[Candidata] = []
    limite = timedelta(minutes=intervalo_min)
    for c in sorted(soltas, key=lambda c: (c.capturado_em, c.rel)):
        if atual:
            anterior = atual[-1]
            if c.capturado_em - anterior.capturado_em > limite or (c.tipo == "video" and anterior.tipo == "foto"):
                grupos.append(atual)
                atual = []
        atual.append(c)
    if atual:
        grupos.append(atual)
    grupos.sort(key=lambda g: (min(c.capturado_em for c in g), min(c.rel for c in g)))
    return [_ordenar_dentro(g) for g in grupos]


def _normalizar_nome(nome: str) -> str:
    return str(nome).replace("\\", "/").strip().strip("/").casefold()


def grupos_explicitos(candidatas: list[Candidata], grupos, ja_feitas: dict[str, str] | None = None,
                      avisos: list[str] | None = None) -> list[list[Candidata]]:
    """Agrupamento dado pela IA: lista de listas de nomes (ou caminhos relativos) dos arquivos originais.

    ``ja_feitas``: original (nome ou caminho relativo, normalizado) → arquivo final de uma rodada anterior.
    Esses nomes são pulados com aviso, para o mesmo pedido poder rodar de novo sem erro.
    """
    if not isinstance(grupos, list) or not all(isinstance(g, list) and all(isinstance(n, str) for n in g) for g in grupos):
        raise ErroPasta('"grupos" tem que ser uma lista de listas de nomes de arquivo, ex.: [["IMG_1.MOV", "IMG_2.JPG"], ["IMG_3.JPG"]]')
    ja_feitas = ja_feitas or {}
    por_rel = {_normalizar_nome(c.rel): [c] for c in candidatas}
    por_nome: dict[str, list[Candidata]] = {}
    for c in candidatas:
        por_nome.setdefault(_normalizar_nome(Path(c.rel).name), []).append(c)
    disponiveis = ", ".join(c.rel for c in candidatas) or "nenhuma"
    usados: set[str] = set()
    saida = []
    for g in grupos:
        lista = []
        for nome in g:
            chave = _normalizar_nome(nome)
            achados = por_rel.get(chave) or por_nome.get(chave) or []
            if not achados and chave in ja_feitas:
                if avisos is not None:
                    avisos.append(f"Grupos: {nome} já tinha virado {ja_feitas[chave]} numa rodada anterior: pulado")
                continue
            if not achados:
                raise ErroPasta(f"Grupos: não encontrei '{nome}' entre as mídias novas. Mídias novas: {disponiveis}")
            if len(achados) > 1:
                raise ErroPasta(f"Grupos: '{nome}' existe em mais de uma subpasta ({', '.join(c.rel for c in achados)}). "
                                "Use o caminho relativo.")
            c = achados[0]
            if c.rel in usados:
                raise ErroPasta(f"Grupos: '{nome}' aparece em mais de um grupo")
            usados.add(c.rel)
            lista.append(c)
        if lista:
            saida.append(_ordenar_dentro(lista))
    faltando = [c.rel for c in candidatas if c.rel not in usados]
    if faltando:
        raise ErroPasta(f"Grupos: mídias novas fora dos grupos: {', '.join(faltando)}. Inclua cada uma em algum grupo.")
    return saida


def _ja_feitas(pasta: Path, reg: Registro) -> dict[str, str]:
    """Originais que já viraram arquivo final (por caminho relativo e por nome, normalizados)."""
    feitas: dict[str, str] = {}
    for e in reg.entradas:
        if e.get("origem") and e.get("arquivo") and (pasta / e["arquivo"]).exists():
            feitas[_normalizar_nome(e["origem"])] = e["arquivo"]
            feitas.setdefault(_normalizar_nome(Path(e["origem"]).name), e["arquivo"])
    return feitas


def _planejar(candidatas: list[Candidata], existentes: list[Letra], reservadas: set[str], cfg: dict, grupos=None,
              ja_feitas: dict[str, str] | None = None, avisos: list[str] | None = None) -> list[Letra]:
    """Letras novas: próxima letra livre depois da maior existente, em ordem."""
    if not candidatas and grupos is None:
        return []
    if grupos is not None:
        lista = grupos_explicitos(candidatas, grupos, ja_feitas, avisos)
    else:
        lista = agrupar(candidatas, cfg["intervalo_min"])
    usadas = [indice_letra(L.letra) for L in existentes] + [indice_letra(r) for r in reservadas]
    proximo = max(usadas, default=-1) + 1
    novas = []
    for k, grupo in enumerate(lista):
        letra = letra_do_indice(proximo + k)
        midias = []
        for n, c in enumerate(grupo, start=1):
            operacao, ext = _operacao(c.caminho, cfg)
            midias.append(Midia(letra, f"{letra} - {n}{ext}", c.tipo, c.caminho, c.rel, operacao, capturado_em=c.capturado_em))
        novas.append(Letra(letra, True, midias))
    return novas


def _conflitos(pasta: Path, letras: list[Letra]) -> list[str]:
    vistos: set[str] = set()
    conflitos = []
    for L in letras:
        for m in L.midias:
            if not m.operacao:
                continue
            if os.path.lexists(pasta / m.arquivo) or m.arquivo.casefold() in vistos:
                conflitos.append(m.arquivo)
            vistos.add(m.arquivo.casefold())
    return conflitos


# ---------------------------------------------------------------- aplicar

def _mover_original(pasta: Path, entrada: dict, cfg: dict, avisos: list[str]) -> bool:
    """Guarda o original em ``_originais`` (mesma subpasta; nome com sufixo se já existir)."""
    origem = pasta / entrada["origem"]
    destino = _nome_livre(pasta / cfg["originais"] / entrada["origem"])
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        _renomear_sem_sobrescrever(origem, destino)
    except OSError as e:
        motivo = e.strerror or str(e)
        avisos.append(f"Não consegui mover {entrada['origem']} para {cfg['originais']} ({motivo}). "
                      f"{entrada['arquivo']} já está pronto; feche o arquivo e rode de novo para concluir.")
        log.warning("Não consegui mover %s para %s: %s", entrada["origem"], cfg["originais"], motivo)
        return False
    entrada["estado"] = "feito"
    entrada["movido_para"] = _rel(destino, pasta)
    log.info("Original guardado: %s → %s", entrada["origem"], entrada["movido_para"])
    return True


def _nova_entrada(pasta: Path, letra: str, m: Midia) -> dict:
    origem = pasta / m.origem
    return {
        "letra": letra,
        "arquivo": m.arquivo,
        "origem": m.origem,
        "operacao": m.operacao,
        "tipo": m.tipo,
        "tamanho_origem": origem.stat().st_size,
        "hash_origem": midia.hash_arquivo(origem),
        "capturado_em": m.capturado_em.isoformat(timespec="seconds") if m.capturado_em else None,
        "convertido": None,
        "estado": "pendente",
        "movido_para": None,
        "em": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _aplicar_letra(pasta: Path, L: Letra, reg: Registro, cfg: dict, avisos: list[str], prontas: list[str]) -> None:
    """Cria todos os finais da letra; se algum falhar, desfaz os que criou e nada muda na letra.
    Só depois de todos prontos os originais vão para ``_originais``."""
    pendentes = [m for m in L.midias if m.operacao]
    entradas = []
    for m in pendentes:
        try:
            entradas.append(_nova_entrada(pasta, L.letra, m))
        except OSError as erro:  # ex.: original travado por outro programa no Windows
            raise ErroPasta(
                f"Letra {L.letra}: não consegui ler {m.origem} ({erro.strerror or erro}). "
                f"Nada foi alterado na letra {L.letra}."
                + (f" Letras já prontas: {', '.join(prontas)}." if prontas else "")
                + " Feche o arquivo e rode de novo.",
                {"letras_prontas": list(prontas), "falhou": L.letra},
            ) from erro
    reg.entradas.extend(entradas)
    reg.gravar()  # intenção gravada antes: uma rodada interrompida é retomada na próxima
    criados: list[Path] = []
    atual = None
    try:
        for m, e in zip(pendentes, entradas):
            atual = m
            destino = pasta / m.arquivo
            m.convertido = _criar_final(pasta / m.origem, destino, m.operacao, cfg)
            criados.append(destino)
            e["convertido"], e["estado"] = m.convertido, "criado"
            log.info("%s → %s%s", m.origem, m.arquivo, f" ({m.convertido})" if m.convertido else "")
    except Exception as erro:
        for p in criados:
            _remover_nosso(p)  # cópias/conversões feitas agora; os originais estão intactos
        reg.remover(entradas)
        reg.gravar()
        existente = (erro.filename2 or erro.filename) if isinstance(erro, FileExistsError) else None
        motivo = f"{Path(existente).name} já existe, não vou sobrescrever" if existente else str(erro)
        raise ErroPasta(
            f"Letra {L.letra}: falhou em {atual.origem} → {atual.arquivo} ({motivo or erro.__class__.__name__}). "
            f"Nada foi alterado na letra {L.letra}."
            + (f" Letras já prontas: {', '.join(prontas)}." if prontas else "")
            + " Resolva e rode de novo.",
            {"letras_prontas": list(prontas), "falhou": L.letra},
        ) from erro
    reg.gravar()
    for m, e in zip(pendentes, entradas):
        m.fonte = pasta / m.arquivo
        _mover_original(pasta, e, cfg, avisos)
    reg.gravar()


def _retomar(pasta: Path, reg: Registro, cfg: dict, avisos: list[str]) -> set[str]:
    """Conclui renomeações de uma rodada interrompida (queda, arquivo aberto). Devolve as letras retomadas."""
    retomadas: set[str] = set()
    for e in list(reg.pendentes()):
        origem, destino = pasta / e["origem"], pasta / e["arquivo"]
        if origem.is_file() and _mesmo_original(origem, e):
            if not destino.exists():
                try:
                    e["convertido"] = _criar_final(origem, destino, e["operacao"], cfg)
                except Exception as erro:
                    raise ErroPasta(f"Não consegui concluir a renomeação interrompida {e['origem']} → {e['arquivo']}: {erro}") from erro
                e["estado"] = "criado"
                reg.gravar()
                log.info("Retomado: %s → %s", e["origem"], e["arquivo"])
            _mover_original(pasta, e, cfg, avisos)
            retomadas.add(e["letra"])
        elif destino.exists():
            e["estado"] = "feito"  # o original saiu da pasta por outro caminho; o final está lá
        else:
            reg.remover([e])
            avisos.append(f"Renomeação interrompida descartada: {e['origem']} → {e['arquivo']} (o original não está mais na pasta)")
    reg.gravar()
    if retomadas:
        log.info("Rodada anterior interrompida: concluí a(s) letra(s) %s", ", ".join(sorted(retomadas, key=indice_letra)))
    return retomadas


def _limpar_subpastas(pasta: Path, subpastas: set[str]) -> None:
    """Remove subpastas que ficaram vazias depois de guardar os originais (só pasta vazia)."""
    for sub in subpastas:
        raiz = pasta / sub
        if not raiz.is_dir():
            continue
        dirs = sorted((d for d in raiz.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True)
        for d in dirs + [raiz]:
            try:
                d.rmdir()
            except OSError:
                pass


# ---------------------------------------------------------------- descrição e folha de contato

def _modo_previsto(info: midia.InfoMidia) -> str:
    """O que ``midia.converter_para_mp4`` vai fazer (só para a simulação)."""
    video_ok = info.codec_video == "h264" and not info.hdr and info.pix_fmt in (None, "yuv420p", "yuvj420p")
    audio_ok = (not info.tem_audio) or info.codec_audio == "aac"
    return "remux" if video_ok and audio_ok else "recodificado"


def _duracao_txt(segundos: float | None) -> str:
    total = int(round(segundos or 0))
    return f"{total // 60}:{total % 60:02d}"


AUDIO_TXT = {"sem_audio": "sem áudio", "silencioso": "áudio em silêncio", "com_audio": "com áudio"}


@functools.lru_cache(maxsize=1)
def _simbolo_video() -> str:
    """🎥 se a fonte da folha tiver o desenho; senão "VÍDEO"."""
    f = folha.fonte(40)
    try:
        emoji = f.getmask("\U0001F3A5").tobytes()
        ausente = f.getmask("\U0010FFFD").tobytes()
    except Exception:
        return "VÍDEO"
    return "\U0001F3A5" if emoji and emoji != ausente else "VÍDEO"


def _miniatura(caminho: Path, lado: int) -> tuple[Image.Image, tuple[int, int]]:
    """(miniatura já na orientação certa, (largura, altura) reais). Solta o arquivo logo
    (no Windows, arquivo aberto não pode ser movido)."""
    img = midia.abrir_imagem(caminho)
    try:
        tamanho = img.size
        mini = img.convert("RGB")
    finally:
        img.close()
    mini.thumbnail((lado, lado), Image.LANCZOS)
    return mini, tamanho


def _com_faixa(img: Image.Image, texto: str) -> Image.Image:
    altura = max(36, img.height // 8)
    saida = Image.new("RGB", (img.width, img.height + altura), (0, 0, 0))
    saida.paste(img, (0, 0))
    ImageDraw.Draw(saida).text((altura // 3, img.height + altura // 6), texto, font=folha.fonte(int(altura * 0.7)),
                               fill=(255, 235, 59))
    return saida


def _tira_video(caminho: Path, duracao: float | None, audio: str, cf: dict) -> Image.Image:
    """Quadros do vídeo lado a lado + faixa com duração e situação do áudio."""
    quadros = []
    with tempfile.TemporaryDirectory(prefix="folha-") as tmp:
        for i, frac in enumerate(cf["quadros_video"]):
            try:
                q = midia.extrair_quadro(caminho, (duracao or 0) * float(frac), Path(tmp) / f"q{i}.jpg", largura=480)
                with Image.open(q) as im:
                    quadros.append(im.convert("RGB"))
            except (midia.ErroMidia, ferramentas.ErroComando) as e:
                log.warning("Sem quadro em %.0f%% de %s: %s", float(frac) * 100, caminho.name, e)
    if not quadros:
        quadros = [Image.new("RGB", (270, 480), (60, 60, 60))]
    texto = f"{_simbolo_video()} {_duracao_txt(duracao)} · {AUDIO_TXT.get(audio, audio)}"
    return _com_faixa(folha.tira(quadros), texto)


def _descrever(m: Midia, pasta: Path, simular: bool, cfg: dict, avisos: list[str]) -> tuple[dict, Image.Image]:
    """Entrada do manifesto + imagem da folha de contato."""
    final = pasta / m.arquivo
    pronto = final.exists() and not (simular and m.operacao)
    fonte = final if pronto else m.fonte
    cf = cfg["folha"]
    convertido = m.convertido
    if m.tipo == "video":
        info = midia.sondar(fonte)
        audio = midia.situacao_audio(fonte)
        largura, altura, duracao = info.largura, info.altura, info.duracao_s
        imagem = _tira_video(fonte, duracao, audio, cf)
        if not pronto and m.operacao == "mp4":
            convertido = _modo_previsto(info)
        if audio == "sem_audio":
            avisos.append(f"{m.nome} é vídeo sem áudio: vai receber música do Instagram")
        elif audio == "silencioso":
            avisos.append(f"{m.nome} é vídeo com áudio em silêncio: vai receber música do Instagram")
        if (pronto or m.operacao == "copia") and info.codec_video != "h264":
            avisos.append(f"{m.arquivo} está em {info.codec_video} (não é H.264): se não aparecer na galeria do Instagram, converta")
    else:
        imagem, (largura, altura) = _miniatura(fonte, int(cf["miniatura_px"]))
        audio, duracao = None, None
        if not pronto and m.operacao == "jpg":
            convertido = "recodificado"
    if convertido and "hdr_para_sdr" in convertido:
        avisos.append(f"{m.nome}: vídeo HDR convertido para SDR (confira a cor na folha)")
    if pronto:
        hash_ = midia.hash_arquivo(final)
    elif m.operacao == "copia":
        hash_ = midia.hash_arquivo(fonte)  # a cópia terá o mesmo conteúdo
    else:
        hash_ = None
    capturado = m.capturado_em or midia.data_captura(fonte)
    desc = {
        "nome": m.nome,
        "arquivo": m.arquivo,
        "caminho": str(final),
        "tipo": m.tipo,
        "origem": m.origem,
        "convertido": convertido.split("+")[0] if convertido else None,
        "audio": audio,
        "precisa_musica": audio in ("sem_audio", "silencioso"),
        "duracao_s": duracao,
        "largura": largura,
        "altura": altura,
        "hash": hash_,
        "capturado_em": capturado.isoformat(timespec="seconds"),
    }
    return desc, imagem


def _gerar_folha(letra: str, itens: list[tuple[Image.Image, str]], destino: Path, data: str, cf: dict, tem_video: bool) -> Path:
    n = len(itens)
    linhas = math.ceil(n / int(cf["colunas_max"]))
    colunas = math.ceil(n / linhas)
    celula = tuple(cf["celula_video"] if tem_video else cf["celula_foto"])
    data_br = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
    titulo = f"Letra {letra} — {data_br} — {n} {'mídia' if n == 1 else 'mídias'}"
    return folha.montar(itens, destino, titulo=titulo, colunas=colunas, celula=celula, qualidade=int(cf["qualidade"]))


def _limpar_folhas_antigas(pasta_folhas: Path, letras: set[str]) -> None:
    if not pasta_folhas.is_dir():
        return
    for f in pasta_folhas.glob("*.jpg"):
        if PADRAO_FOLHA.match(f.stem) and f.stem not in letras:
            _remover_nosso(f)


def _gravar_json(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def _sem_repetir(itens: list[str]) -> list[str]:
    return list(dict.fromkeys(itens))


# ---------------------------------------------------------------- API

def _validar_data(data: str) -> None:
    try:
        if not PADRAO_DATA.match(str(data)):
            raise ValueError
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        raise ErroPasta(f"Data inválida: {data!r}. Use AAAA-MM-DD (ex.: 2026-09-22).") from None


def pasta_trabalho(data: str) -> Path:
    return config.pastas().trabalho_stories / data


def preparar(data: str, simular: bool = False, grupos: list[list[str]] | None = None) -> dict:
    """Prepara a pasta do dia e devolve o manifesto (também gravado em ``manifesto.json``).

    ``simular``: só propõe (nomes, folhas, manifesto em ``manifesto-simulado.json``); nada muda na pasta do dia.
    ``grupos``: agrupamento explícito das mídias novas (nomes dos arquivos originais), no lugar da heurística.
    """
    _validar_data(data)
    cfg = _cfg()
    pasta = config.pastas().pasta_do_dia(data)
    if not pasta.is_dir():
        raise ErroPasta(f"Pasta do dia não encontrada: {pasta}")
    trabalho = pasta_trabalho(data)
    _registrar_heif()
    log.info("Preparando %s%s", pasta, " (simulação: nada muda na pasta)" if simular else "")

    avisos: list[str] = []
    reg = Registro(pasta, cfg)
    retomadas = set() if simular else _retomar(pasta, reg, cfg, avisos)
    existentes, soltas, avisos_varredura, minusculas = _varrer(pasta)
    avisos += avisos_varredura
    soltas = _filtrar_registradas(soltas, pasta, reg, cfg, avisos)
    candidatas = [_candidata(arq, sub, pasta) for arq, sub in soltas]
    letras = _letras_existentes(existentes, pasta, reg, retomadas, cfg, avisos)
    reservadas = ({e["letra"] for e in reg.pendentes()} if simular else set()) | minusculas
    letras += _planejar(candidatas, letras, reservadas, cfg, grupos, _ja_feitas(pasta, reg), avisos)

    conflitos = _conflitos(pasta, letras)
    if conflitos and not simular:
        raise ErroPasta(
            f"Não vou sobrescrever: já existe na pasta {', '.join(conflitos)}. Nada foi alterado. "
            "Mova ou renomeie esse(s) arquivo(s) e rode de novo."
        )
    avisos += [f"CONFLITO: {c} já existe na pasta; a rodada real vai parar sem alterar nada" for c in conflitos]

    if not simular:
        prontas: list[str] = []
        for L in letras:
            if any(m.operacao for m in L.midias):
                _aplicar_letra(pasta, L, reg, cfg, avisos, prontas)
                prontas.append(L.letra)
        _limpar_subpastas(pasta, {c.subpasta for c in candidatas if c.subpasta})

    pasta_folhas = trabalho / "folhas"
    saida_letras: dict[str, dict] = {}
    for L in letras:
        descs, itens = [], []
        for m in L.midias:
            desc, imagem = _descrever(m, pasta, simular, cfg, avisos)
            descs.append(desc)
            itens.append((imagem, m.nome.replace(" - ", "-")))
        destino = _gerar_folha(L.letra, itens, pasta_folhas / f"{L.letra}.jpg", data, cfg["folha"],
                               any(m.tipo == "video" for m in L.midias))
        if len(descs) > cfg["max_midias"]:
            avisos.append(f"Letra {L.letra} tem {len(descs)} mídias (máximo {cfg['max_midias']}): confira se não são dois modelos")
        saida_letras[L.letra] = {"nova": L.nova, "folha": str(destino), "midias": descs}
    _limpar_folhas_antigas(pasta_folhas, set(saida_letras))
    if not saida_letras:
        avisos.append(f"Nenhuma mídia encontrada em {pasta}")

    manifesto = {
        "data": data,
        "pasta": str(pasta),
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "simulado": bool(simular),
        "letras": saida_letras,
        "avisos": _sem_repetir(avisos),
    }
    _gravar_json(trabalho / (MANIFESTO_SIMULADO if simular else MANIFESTO), manifesto)
    novas = [k for k, v in saida_letras.items() if v["nova"]]
    log.info("Pasta pronta%s: %d letra(s)%s", " (simulação)" if simular else "", len(saida_letras),
             f", novas: {', '.join(novas)}" if novas else "")
    return manifesto


def carregar_manifesto(data: str) -> dict:
    """Lê o ``manifesto.json`` do dia (o da rodada real)."""
    _validar_data(data)
    arq = pasta_trabalho(data) / MANIFESTO
    if not arq.exists():
        extra = " (só existe o manifesto simulado)" if (arq.parent / MANIFESTO_SIMULADO).exists() else ""
        raise ErroPasta(f"Manifesto não encontrado: {arq}{extra}. Rode antes: python -m rotinas stories-preparar --data {data}")
    return json.loads(arq.read_text(encoding="utf-8-sig"))


def tarefa(args: dict, ctx) -> dict:
    """Pedido ``stories.preparar``: ``{"data": "AAAA-MM-DD", "simular"?: bool, "grupos"?: [[...], ...]}``."""
    if not args.get("data"):
        raise ErroPasta('Pedido stories.preparar sem "data" (AAAA-MM-DD)')
    return preparar(str(args["data"]), simular=bool(args.get("simular")), grupos=args.get("grupos"))


def resumo(manifesto: dict) -> str:
    """Texto curto para o terminal."""
    linhas = []
    if manifesto.get("simulado"):
        linhas.append("SIMULAÇÃO: nada foi alterado na pasta do dia.")
    linhas.append(f"Pasta: {manifesto['pasta']}")
    for letra, info in manifesto["letras"].items():
        nomes = ", ".join(m["arquivo"] + (f" ← {m['origem']}" if info["nova"] and m.get("origem") else "") for m in info["midias"])
        linhas.append(f"  {letra} ({'nova' if info['nova'] else 'já existia'}): {nomes}")
    if manifesto["letras"]:
        linhas.append(f"Folhas: {Path(next(iter(manifesto['letras'].values()))['folha']).parent}")
    nome = MANIFESTO_SIMULADO if manifesto.get("simulado") else MANIFESTO
    linhas.append(f"Manifesto: {pasta_trabalho(manifesto['data']) / nome}")
    if manifesto["avisos"]:
        linhas.append("Avisos:")
        linhas += [f"  - {a}" for a in manifesto["avisos"]]
    return "\n".join(linhas)


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="python -m rotinas stories-preparar",
        description="A1: nomeia as mídias novas na próxima letra livre, converte .mov/HEIC, "
                    "guarda os originais em _originais e gera as folhas de contato.",
    )
    p.add_argument("--data", default=datetime.now().strftime("%Y-%m-%d"), help="pasta do dia, AAAA-MM-DD (padrão: hoje)")
    p.add_argument("--simular", action="store_true", help="só mostra o que faria (gera folhas e manifesto-simulado.json)")
    p.add_argument("--grupos", help='agrupamento em JSON, ex.: [["IMG_1.MOV","IMG_2.JPG"],["IMG_3.JPG"]]')
    p.add_argument("--grupos-arquivo", help="arquivo JSON com o agrupamento")
    p.add_argument("--json", action="store_true", help="imprime o manifesto completo em JSON")
    a = p.parse_args(argv)
    try:
        grupos = None
        if a.grupos_arquivo:
            grupos = json.loads(Path(a.grupos_arquivo).read_text(encoding="utf-8-sig"))
        elif a.grupos:
            grupos = json.loads(a.grupos)
        manifesto = preparar(a.data, simular=a.simular, grupos=grupos)
    except (ErroPasta, midia.ErroMidia, ferramentas.FerramentaAusente, ferramentas.ErroComando,
            config.ErroConfig, ValueError, OSError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    print(json.dumps(manifesto, ensure_ascii=False, indent=2) if a.json else resumo(manifesto))
    return 0
