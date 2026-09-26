"""A3: registro do que já foi postado nos stories e varredura das pastas de data.

Regra fixa 2 (``conhecimento/stories.md``): não repetir modelo nem mídia.
- ``registros/postados.csv``: uma linha por mídia publicada, gravada só DEPOIS de publicar.
  UTF-8 com BOM e ``;`` (abre certo no Excel). Só acrescenta linhas, nunca reescreve o arquivo.
- ``registros/postados_pendentes/*.json``: letra publicada cujo registro no CSV falhou (ex.: Excel aberto).
  ``ler``/``letras_postadas``/``verificar`` contam essas letras como publicadas; o próximo ``registrar``
  que conseguir gravar passa as pendentes para o CSV e apaga os arquivos.
- Varredura das outras pastas de data (``AAAA-MM-DD``, incluindo ``_originais``) pelo hash das
  mídias, com cache em ``registros/cache_hashes.json`` (caminho + tamanho + data de modificação).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .. import config, midia, registro

log = registro.obter("stories.postados")

COLUNAS = ["data", "letra", "sku", "cor", "arquivo", "hash", "peca", "pedido", "registrado_em"]
OBRIGATORIAS = COLUNAS[:6]  # as do BRIEFING
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_DATA_BR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
RE_LETRA = re.compile(r"^[A-Z]{1,2}$")
RE_NOME = re.compile(r"^(?P<letra>[A-Z]{1,2}) - (?P<n>\d+)\.(?P<ext>[A-Za-z0-9]+)$")
BOM = b"\xef\xbb\xbf"


class ErroPostados(RuntimeError):
    """Problema com o registro de já postados."""

    def __init__(self, mensagem: str, **extras):
        super().__init__(mensagem)
        for chave, valor in extras.items():
            setattr(self, chave, valor)


def _cfg_stories() -> dict:
    try:
        return config.carregar("stories")
    except config.ErroConfig:
        return {}


def caminho_csv() -> Path:
    return config.pastas().registros / ((_cfg_stories().get("postados") or {}).get("arquivo") or "postados.csv")


def pasta_pendentes() -> Path:
    return config.pastas().registros / ((_cfg_stories().get("postados") or {}).get("pasta_pendentes") or "postados_pendentes")


def caminho_cache() -> Path:
    return config.pastas().registros / ((_cfg_stories().get("postados") or {}).get("cache_hashes") or "cache_hashes.json")


def _pasta_originais() -> str:
    return _cfg_stories().get("pasta_originais") or "_originais"


# ---------------------------------------------------------------- datas

def data_br(data: str) -> str:
    """``"2026-09-22"`` → ``"22/09/2026"``."""
    try:
        return datetime.strptime(str(data), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(data)


def _normalizar_data(texto) -> str:
    """Aceita também ``22/09/2026`` (o Excel troca o formato se o arquivo for salvo por ele)."""
    t = str(texto or "").strip()
    m = RE_DATA_BR.match(t)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return t[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", t) else t


def _validar_data(data) -> str:
    d = str(data or "").strip()
    try:
        if not RE_DATA.match(d):
            raise ValueError
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise ErroPostados(f"Data inválida: {data!r} (use AAAA-MM-DD, ex.: 2026-09-22)") from None
    return d


# ---------------------------------------------------------------- CSV

def _msg_aberto(caminho: Path, acao: str) -> str:
    return (
        f"Não consegui {acao} {caminho}: o arquivo está aberto em outro programa (provavelmente no Excel). "
        "Feche o arquivo e tente de novo."
    )


def _decodificar(bruto: bytes) -> tuple[str, str]:
    """Texto e codificação: UTF-8 (com ou sem BOM) ou cp1252, se o Excel regravou o arquivo.

    Sem BOM e só com ASCII, o arquivo foi regravado pelo Excel ("CSV separado por ponto e vírgula",
    que é cp1252): o que for acrescentado vai em cp1252, senão o Excel mostra "AlÃ§a" e, ao salvar de
    novo, grava o texto estragado.
    """
    if not bruto.startswith(BOM) and bruto.isascii():
        return bruto.decode("ascii"), "cp1252"
    try:
        return bruto.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return bruto.decode("cp1252", errors="replace"), "cp1252"


def _delimitador(primeira_linha: str) -> str:
    return "," if ";" not in primeira_linha and "," in primeira_linha else ";"


def _analisar(texto: str) -> tuple[list[str], list[dict]]:
    """Cabeçalho (em minúsculas) e linhas como dicts com todas as ``COLUNAS``."""
    if not texto.strip():
        return [], []
    primeira = texto.splitlines()[0]
    linhas = list(csv.reader(io.StringIO(texto, newline=""), delimiter=_delimitador(primeira)))
    cabecalho = [c.strip().lstrip("﻿").lower() for c in linhas[0]]
    registros = []
    for valores in linhas[1:]:
        if not any(v.strip() for v in valores):
            continue
        d = {c: "" for c in COLUNAS}
        for c, v in zip(cabecalho, valores):
            if c:
                d[c] = v.strip()
        d["data"] = _normalizar_data(d["data"])
        d["letra"] = d["letra"].upper()
        d["hash"] = d["hash"].lower()
        registros.append(d)
    return cabecalho, registros


def _ler_bytes(caminho: Path) -> bytes:
    try:
        return caminho.read_bytes()
    except PermissionError as e:
        raise ErroPostados(_msg_aberto(caminho, "ler")) from e


def ler() -> list[dict]:
    """Todas as linhas de ``postados.csv`` mais as dos registros pendentes (letra publicada que não
    conseguiu ser gravada no CSV). Vazio se não há nenhum dos dois."""
    caminho = caminho_csv()
    linhas = []
    if caminho.exists():
        texto, _ = _decodificar(_ler_bytes(caminho))
        linhas = _analisar(texto)[1]
    ja = {_chave_linha(l) for l in linhas}
    for _, pendentes in ler_pendentes():
        for l in pendentes:
            if _chave_linha(l) not in ja:
                ja.add(_chave_linha(l))
                linhas.append(l)
    return linhas


def _chave_linha(l: dict) -> tuple:
    return (l["data"], l["letra"], l["arquivo"].casefold(), l["hash"])


# ---------------------------------------------------------------- pendentes

def ler_pendentes() -> list[tuple[Path, list[dict]]]:
    """Registros pendentes: ``[(arquivo .json, linhas no formato do CSV)]``.

    Pendente ilegível → ``ErroPostados``: sem saber se a letra subiu, nada deve ser publicado.
    """
    pasta = pasta_pendentes()
    if not pasta.is_dir():
        return []
    saida = []
    for arq in sorted(pasta.glob("*.json")):
        try:
            dados = json.loads(arq.read_text(encoding="utf-8-sig"))
            brutas = dados["linhas"]
            if not isinstance(brutas, list):
                raise ValueError("'linhas' não é uma lista")
        except PermissionError as e:
            raise ErroPostados(_msg_aberto(arq, "ler")) from e
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ErroPostados(f"Registro pendente ilegível: {arq} ({e}). Conferir no Instagram se a letra subiu e "
                               "corrigir ou apagar o arquivo antes de postar de novo.") from e
        linhas = []
        for b in brutas:
            d = {c: str((b or {}).get(c) or "").strip() for c in COLUNAS}
            d["data"], d["letra"], d["hash"] = _normalizar_data(d["data"]), d["letra"].upper(), d["hash"].lower()
            linhas.append(d)
        saida.append((arq, linhas))
    return saida


def gravar_pendente(data: str, letra: str, linhas: list[dict]) -> Path:
    """Guarda na pasta central as linhas de uma letra publicada que não entraram no CSV."""
    pasta = pasta_pendentes()
    pasta.mkdir(parents=True, exist_ok=True)
    base = f"{data}_{letra}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    destino = pasta / f"{base}.json"
    n = 2
    while destino.exists():
        destino = pasta / f"{base}_{n}.json"
        n += 1
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(json.dumps({"data": data, "letra": letra, "linhas": linhas}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, destino)
    log.warning("Registro pendente gravado em %s (conta como já publicado até entrar no postados.csv)", destino)
    return destino


def _descarregar_pendentes(caminho: Path) -> None:
    """Passa os pendentes para o CSV (sem duplicar) e apaga os arquivos já gravados."""
    for arq, linhas in ler_pendentes():
        _acrescentar(caminho, linhas)
        try:
            arq.unlink()
        except OSError as e:  # continua contando pelo arquivo; o CSV não duplica
            log.warning("Gravei o pendente %s no postados.csv, mas não consegui apagá-lo: %s", arq.name, e)
        else:
            log.info("Pendente %s gravado no postados.csv", arq.name)


def testar_gravacao(tentativas: int = 3, espera_s: float = 1.0) -> None:
    """Confere, antes de publicar, que dá para gravar no ``postados.csv`` e na pasta de pendentes.

    Não muda nada: abre o CSV para acrescentar e fecha sem escrever (o Excel bloqueia isso). Se não
    der, ``ErroPostados``.
    """
    caminho = caminho_csv()
    tentativas = max(1, int(tentativas))
    for tentativa in range(1, tentativas + 1):
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            pasta_pendentes().mkdir(parents=True, exist_ok=True)
            if caminho.exists():
                with open(caminho, "ab"):
                    pass
            return
        except PermissionError as e:
            if tentativa == tentativas:
                raise ErroPostados(_msg_aberto(caminho, "gravar em")) from e
            log.warning("postados.csv ocupado (tentativa %d de %d); tentando de novo", tentativa, tentativas)
            time.sleep(espera_s)
        except OSError as e:
            raise ErroPostados(f"Não consigo gravar o registro de já postados ({caminho}): {e}") from e


def _acrescentar(caminho: Path, linhas: list[dict]) -> int:
    """Acrescenta as linhas que ainda não estão no arquivo (mesma data, letra, arquivo e hash).

    Rodar de novo o mesmo registro (retomada de uma postagem) não duplica nada. Devolve quantas gravou.
    """
    bruto = caminho.read_bytes() if caminho.exists() else b""
    if not bruto.replace(BOM, b"").strip():
        # arquivo novo (ou vazio): BOM + cabeçalho
        with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(COLUNAS)
            w.writerows([l[c] for c in COLUNAS] for l in linhas)
        return len(linhas)
    texto, codificacao = _decodificar(bruto)
    cabecalho, existentes = _analisar(texto)
    faltam = [c for c in OBRIGATORIAS if c not in cabecalho]
    if faltam:
        raise ErroPostados(f"{caminho} está com o cabeçalho inesperado (faltam: {', '.join(faltam)}). Não mexi no arquivo.")
    ja = {_chave_linha(l) for l in existentes}
    novas = [l for l in linhas if _chave_linha(l) not in ja]
    if not novas:
        return 0
    with open(caminho, "a", encoding=codificacao, errors="replace", newline="") as f:
        if not bruto.endswith(b"\n"):
            f.write("\r\n")
        w = csv.writer(f, delimiter=_delimitador(texto.splitlines()[0]))
        w.writerows([l.get(c, "") for c in cabecalho] for l in novas)
    return len(novas)


def registrar(
    data: str,
    letra: str,
    sku: str | None,
    peca: str | None,
    midias: list[dict],
    pedido: str | None,
    *,
    tentativas: int = 3,
    espera_s: float = 1.0,
) -> int:
    """Acrescenta uma linha por mídia publicada. ``midias = [{"arquivo"|"nome", "cores": [...], "hash"}]``.

    Devolve quantas linhas gravou. Arquivo aberto no Excel → tenta de novo e, se continuar
    preso, ``ErroPostados`` (com as linhas não gravadas em ``erro.linhas``). Antes, passa para o CSV
    os registros pendentes (``registros/postados_pendentes``).
    """
    linhas = linhas_do_registro(data, letra, sku, peca, midias, pedido)
    data, letra = _validar_data(data), str(letra or "").strip().upper()
    if not linhas:
        log.warning("Nada para registrar (letra %s de %s sem mídias)", letra, data)
        return 0
    caminho = caminho_csv()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tentativas = max(1, int(tentativas))
    for tentativa in range(1, tentativas + 1):
        try:
            try:
                _descarregar_pendentes(caminho)
            except ErroPostados as e:  # pendente ilegível: não impede gravar esta letra
                log.warning("Não consegui passar os pendentes para o postados.csv: %s", e)
            gravadas = _acrescentar(caminho, linhas)
            break
        except PermissionError as e:
            if tentativa == tentativas:
                raise ErroPostados(
                    _msg_aberto(caminho, "gravar")
                    + f" A letra {letra} de {data_br(data)} ({len(linhas)} mídia(s)) ficou sem registro.",
                    linhas=linhas,
                ) from e
            log.warning("postados.csv ocupado (tentativa %d de %d); tentando de novo", tentativa, tentativas)
            time.sleep(espera_s)
    if gravadas < len(linhas):
        log.info("postados.csv: %d mídia(s) da letra %s de %s já estavam registradas", len(linhas) - gravadas, letra, data)
    log.info("Registrado em postados.csv: %s letra %s, %s, %d mídia(s)", data, letra, sku or "sem SKU", gravadas)
    return gravadas


def linhas_do_registro(data: str, letra: str, sku: str | None, peca: str | None, midias: list[dict],
                       pedido: str | None) -> list[dict]:
    """Linhas do CSV (uma por mídia) de uma letra publicada agora."""
    data = _validar_data(data)
    letra = str(letra or "").strip().upper()
    if not RE_LETRA.match(letra):
        raise ErroPostados(f"Letra inválida: {letra!r}")
    agora = datetime.now().astimezone().isoformat(timespec="seconds")
    linhas = []
    for m in midias or []:
        cores = m.get("cores") or []
        if isinstance(cores, str):
            cores = [cores]
        linhas.append({
            "data": data,
            "letra": letra,
            "sku": str(sku or "").strip(),
            "cor": ", ".join(str(c).strip() for c in cores if str(c or "").strip()),
            "arquivo": str(m.get("arquivo") or m.get("nome") or "").strip(),
            "hash": str(m.get("hash") or "").strip().lower(),
            "peca": str(peca or "").strip(),
            "pedido": str(pedido or "").strip(),
            "registrado_em": agora,
        })
    return linhas


def letras_postadas(data: str) -> set[str]:
    """Letras do dia que já têm registro (já publicadas), inclusive as pendentes de gravar no CSV."""
    data = _normalizar_data(data)
    return {l["letra"] for l in ler() if l["data"] == data and l["letra"]}


# ---------------------------------------------------------------- cache de hashes

class CacheHashes:
    """Hash de cada arquivo, reaproveitado enquanto caminho, tamanho e data de modificação não mudam."""

    VERSAO = 1

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.arquivos: dict[str, dict] = {}
        self.calculados = 0
        self._mudou = False
        if self.caminho.exists():
            try:
                dados = json.loads(self.caminho.read_text(encoding="utf-8"))
                if isinstance(dados, dict) and isinstance(dados.get("arquivos"), dict):
                    self.arquivos = dados["arquivos"]
            except (OSError, ValueError) as e:
                log.warning("Cache de hashes ilegível (%s); vou recalcular", e)

    def hash(self, arquivo: Path) -> str:
        st = arquivo.stat()
        chave = str(arquivo)
        e = self.arquivos.get(chave)
        if isinstance(e, dict) and e.get("hash") and e.get("tamanho") == st.st_size and e.get("mtime_ns") == st.st_mtime_ns:
            return e["hash"]
        h = midia.hash_arquivo(arquivo)
        self.arquivos[chave] = {"tamanho": st.st_size, "mtime_ns": st.st_mtime_ns, "hash": h}
        self.calculados += 1
        self._mudou = True
        return h

    def salvar(self) -> None:
        sumidos = [c for c in self.arquivos if not Path(c).exists()]
        for c in sumidos:
            del self.arquivos[c]
        if not (self._mudou or sumidos):
            return
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.caminho.with_name(self.caminho.name + ".tmp")
            tmp.write_text(json.dumps({"versao": self.VERSAO, "arquivos": self.arquivos}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.caminho)
            self._mudou = False
        except OSError as e:
            log.warning("Não consegui gravar o cache de hashes (%s); fica para a próxima", e)


# ---------------------------------------------------------------- verificação

def _ocorrencia(motivo: str, data: str, letra: str | None, arquivo: str, hash_: str | None = None, sku: str = "") -> dict:
    onde = data_br(data) + (f", letra {letra}" if letra else "") + (f" ({arquivo})" if arquivo else "")
    if motivo == "sku":
        texto = f"modelo {sku} já postado em {onde}"
    elif motivo == "hash_registro":
        texto = f"mesma mídia já postada em {onde}"
    else:
        texto = f"mesma mídia já está na pasta de {onde}"
    oc = {"motivo": motivo, "data": data, "letra": letra, "arquivo": arquivo, "texto": texto}
    if hash_:
        oc["hash"] = hash_
    return oc


def _pastas_de_data(exceto: str) -> list[Path]:
    raiz = config.pastas().stories_fonte
    if not raiz.is_dir():
        return []
    return sorted(p for p in raiz.iterdir() if p.is_dir() and RE_DATA.match(p.name) and p.name != exceto)


def _eh_midia_valida(a: Path) -> bool:
    return (
        a.is_file()
        and not a.name.startswith((".", "~$"))
        and ".parcial." not in a.name
        and (midia.eh_foto(a) or midia.eh_video(a))
    )


def _midias_da_pasta(pasta: Path) -> list[Path]:
    """Mídias da pasta do dia (primeiro as da raiz) e das subpastas, inclusive ``_originais``.

    A preparação guarda o original em ``_originais/<mesma subpasta>/``, então a busca é recursiva.
    """
    try:
        todos = [a for a in pasta.rglob("*") if _eh_midia_valida(a)]
    except OSError as e:
        log.warning("Não consegui listar %s: %s", pasta, e)
        return []
    return sorted(todos, key=lambda a: (a.parent != pasta, a.relative_to(pasta).as_posix().lower()))


def _ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _renomeacoes(pasta: Path) -> list[dict]:
    """Entradas de ``<pasta do dia>/_originais/renomeados.json`` (gravado pela preparação da pasta)."""
    nome = (_cfg_stories().get("preparar") or {}).get("registro_renomeacoes") or "renomeados.json"
    dados = _ler_json(pasta / _pasta_originais() / nome)
    entradas = dados.get("entradas") if isinstance(dados, dict) else None
    return [e for e in entradas or [] if isinstance(e, dict)]


def _origens(pasta: Path) -> dict[str, tuple[str, str]]:
    """Caminho relativo (ou só o nome) do original, em minúsculas → (letra, arquivo renomeado).

    Fontes: ``_originais/renomeados.json`` da pasta (tem o destino real, com sufixo "(2)" quando o nome
    já existia) e o ``manifesto.json`` daquele dia.
    """
    mapa: dict[str, tuple[str, str]] = {}
    dados = _ler_json(config.pastas().trabalho_stories / pasta.name / "manifesto.json")
    letras = dados.get("letras") if isinstance(dados, dict) else None
    for letra, info in (letras if isinstance(letras, dict) else {}).items():
        midias = info.get("midias") if isinstance(info, dict) else None
        for m in midias or []:
            if isinstance(m, dict) and m.get("origem"):
                valor = (str(letra), str(m.get("arquivo") or m.get("nome") or ""))
                origem = str(m["origem"]).replace("\\", "/").lower()
                mapa.setdefault(origem.rsplit("/", 1)[-1], valor)
                mapa[f"{_pasta_originais().lower()}/{origem}"] = valor
    for e in _renomeacoes(pasta):
        if not (e.get("letra") and e.get("arquivo")):
            continue
        valor = (str(e["letra"]), str(e["arquivo"]))
        for chave in (e.get("movido_para"), e.get("origem")):
            if chave:
                chave = str(chave).replace("\\", "/").lower()
                mapa[chave] = valor
                mapa.setdefault(chave.rsplit("/", 1)[-1], valor)
    return mapa


def _hashes_originais(data: str, letra: str) -> set[str]:
    """Hash dos originais (antes de converter) das mídias desta letra no próprio dia.

    Um ``.MOV`` convertido para ``.mp4`` pode sair com bytes diferentes em outro dia (outra versão do
    ffmpeg); o original guardado em ``_originais`` não muda, então ele também é procurado.
    """
    return {
        str(e["hash_origem"]).lower()
        for e in _renomeacoes(config.pastas().pasta_do_dia(data))
        if str(e.get("letra") or "").upper() == letra and e.get("hash_origem")
    }


def _varrer_pastas(data: str, procurados: set[str], ja_registro: set[tuple], vistos: set[tuple]) -> list[dict]:
    cache = CacheHashes(caminho_cache())
    achados = []
    try:
        for pasta in _pastas_de_data(data):
            origens = None
            for arq in _midias_da_pasta(pasta):
                try:
                    h = cache.hash(arq)
                except OSError as e:
                    log.warning("Não consegui ler %s para comparar: %s", arq, e)
                    continue
                if h not in procurados or (pasta.name, h) in vistos:
                    continue
                m = RE_NOME.match(arq.name) if arq.parent == pasta else None
                if m:
                    letra, nome = m.group("letra"), arq.name
                else:
                    if origens is None:
                        origens = _origens(pasta)
                    rel = arq.relative_to(pasta)
                    chave = rel.as_posix().lower()
                    letra, nome = origens.get(chave) or origens.get(arq.name.lower()) or (None, str(rel))
                vistos.add((pasta.name, h))
                if letra and (pasta.name, letra) in ja_registro:
                    continue  # essa postagem já apareceu pelo registro
                achados.append(_ocorrencia("hash_pasta", pasta.name, letra, nome, hash_=h))
    finally:
        cache.salvar()
    if cache.calculados:
        log.info("Hash calculado de %d arquivo(s) das pastas de data (os outros vieram do cache)", cache.calculados)
    return achados


def verificar(data: str, letra: str, sku: str | None, hashes: list[str]) -> list[dict]:
    """Ocorrências de repetição para a letra ``letra`` do dia ``data`` (lista vazia = pode postar).

    - ``sku``: o mesmo modelo em qualquer registro de outra data, ou da mesma data em outra letra;
    - ``hash_registro``: a mesma mídia (hash) num registro (CSV ou pendente);
    - ``hash_pasta``: a mesma mídia numa outra pasta de data (inclui ``_originais`` e subpastas).

    Além de ``hashes``, procura também os originais desta letra (``_originais/renomeados.json``).

    A própria letra no mesmo dia não bloqueia a si mesma (o CSV só recebe linha depois de
    publicar); para não postar de novo uma letra já publicada, use ``letras_postadas``.
    """
    data = _validar_data(data)
    letra = str(letra or "").strip().upper()
    sku_alvo = str(sku or "").strip().casefold()
    procurados = {str(h).strip().lower() for h in hashes or [] if str(h or "").strip()}
    procurados |= _hashes_originais(data, letra)
    ocorrencias: list[dict] = []
    ja_registro: set[tuple[str, str]] = set()  # (data, letra) já citados pelo registro
    vistos: set[tuple[str, str]] = set()  # (data, hash) já citados
    for l in ler():
        d, le = l["data"], l["letra"]
        if d == data and le == letra:
            continue
        if sku_alvo and l["sku"].casefold() == sku_alvo:
            if l["hash"]:
                vistos.add((d, l["hash"]))
            if (d, le) not in ja_registro:
                ja_registro.add((d, le))
                ocorrencias.append(_ocorrencia("sku", d, le, l["arquivo"], sku=l["sku"]))
            continue
        if l["hash"] and l["hash"] in procurados and (d, l["hash"]) not in vistos:
            vistos.add((d, l["hash"]))
            ja_registro.add((d, le))
            ocorrencias.append(_ocorrencia("hash_registro", d, le, l["arquivo"], hash_=l["hash"]))
    if procurados:
        ocorrencias += _varrer_pastas(data, procurados, ja_registro, vistos)
    ocorrencias.sort(key=lambda o: (o["data"], o["letra"] or "", o["arquivo"]))
    if ocorrencias:
        log.info("Letra %s de %s: %d ocorrência(s) de repetição", letra, data, len(ocorrencias))
    return ocorrencias


# ---------------------------------------------------------------- terminal

def _agrupar(linhas: list[dict]) -> list[dict]:
    postagens: dict[tuple[str, str], dict] = {}
    for l in linhas:
        p = postagens.setdefault((l["data"], l["letra"]), {
            "data": l["data"], "letra": l["letra"], "sku": l["sku"], "peca": l["peca"], "midias": [],
        })
        p["midias"].append({"arquivo": l["arquivo"], "cor": l["cor"], "hash": l["hash"], "pedido": l["pedido"]})
    return list(postagens.values())


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas stories-postados", description="Consulta o registro de stories já postados.")
    p.add_argument("--sku", help="só as postagens deste SKU")
    p.add_argument("--data", help="só as postagens deste dia (AAAA-MM-DD)")
    p.add_argument("--ultimos", type=int, default=20, help="sem filtro: quantas postagens mostrar (padrão 20)")
    p.add_argument("--json", action="store_true", help="saída em JSON")
    a = p.parse_args(argv)
    try:
        linhas = ler()
    except ErroPostados as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    if a.sku:
        linhas = [l for l in linhas if l["sku"].casefold() == a.sku.strip().casefold()]
    if a.data:
        linhas = [l for l in linhas if l["data"] == _normalizar_data(a.data)]
    postagens = _agrupar(linhas)
    if not (a.sku or a.data):
        postagens = postagens[-max(a.ultimos, 1):]
    if a.json:
        print(json.dumps(postagens, ensure_ascii=False, indent=2))
        return 0
    if not postagens:
        filtro = " ".join(x for x in (f"do SKU {a.sku}" if a.sku else "", f"de {data_br(a.data)}" if a.data else "") if x)
        print(f"Nenhuma postagem registrada{' ' + filtro if filtro else ''} ({caminho_csv()}).")
        return 0
    print(f"{len(postagens)} postagem(ns) em {caminho_csv()}:")
    for po in postagens:
        print(f"{data_br(po['data'])}  letra {po['letra']}  {po['sku'] or '(sem SKU)'}  {po['peca']}")
        print("    " + ", ".join(f"{m['arquivo']} ({m['cor'] or 'sem cor'})" for m in po["midias"]))
    return 0
