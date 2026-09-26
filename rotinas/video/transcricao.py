"""B1: transcrição da fala no próprio PC (faster-whisper) e legendas ``.srt`` pelas regras do guia §5.

Regras dos blocos de legenda (``conhecimento/edicao-video-capcut.md`` §5, parâmetros em ``config/video.json``):
2–4 palavras por bloco, até 2 linhas de até 42 caracteres, até 17 caracteres por segundo, tempo mínimo na tela,
nunca terminar bloco em artigo, preposição ou "R$" (nem separar nome e sobrenome), quebra em pausa > 0,5 s e em
pontuação final, blocos nunca se sobrepõem, preço no formato da loja ("R$ 229,99" falado vira "R$229,99").
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from .. import config, registro

log = registro.obter("video.transcricao")

# Usados só se faltar a chave em config/video.json (a config manda).
PADRAO = {
    "whisper_modelo": "small",
    "whisper_dispositivo": "cpu",
    "whisper_computacao": "int8",
    "whisper_idioma": "pt",
    "whisper_prompt": "",
    "whisper_pasta_modelos": None,
    "legenda_max_palavras": 4,
    "legenda_max_caracteres_linha": 42,
    "legenda_max_linhas": 2,
    "legenda_max_cps": 17,
    "legenda_min_s": 1.0,
    "legenda_pausa_s": 0.5,
    "legenda_quebra_virgula": True,
    "legenda_emendar_s": 0.3,
    "palavras_que_nao_fecham_bloco": [],
}

_TAMANHOS = {"tiny": "~75 MB", "base": "~145 MB", "small": "~480 MB", "medium": "~1,5 GB",
             "large-v2": "~3 GB", "large-v3": "~3 GB", "turbo": "~1,6 GB", "large-v3-turbo": "~1,6 GB"}

FINAL = (".", "!", "?", "…")
VIRGULA = (",", ";", ":")
_FECHA_ASPAS = "\"'”’)»]"
_BORDAS = "\"'“”‘’()[]{}«»,.;:!?…-–—"

_modelos: dict[tuple, object] = {}


class ErroTranscricao(RuntimeError):
    """Não deu para transcrever."""


class ModeloIndisponivel(ErroTranscricao):
    """Whisper sem instalar ou modelo que não carregou: nada será transcrito nesta rodada."""


class WhisperAusente(ModeloIndisponivel):
    """O pacote faster-whisper não está instalado."""


def _cfg() -> dict:
    try:
        dados = config.carregar("video")
    except config.ErroConfig:
        dados = {}
    return {**PADRAO, **dados}


# ---------------------------------------------------------------- faster-whisper

def _precisa_baixar(nome: str, pasta: str | None) -> bool:
    if Path(nome).is_dir():
        return False
    try:
        from faster_whisper.utils import download_model  # type: ignore

        download_model(nome, local_files_only=True, cache_dir=pasta)
        return False
    except Exception:
        return True


def carregar_modelo(modelo: str | None = None):
    """Modelo Whisper (um por processo: fica em cache para os próximos arquivos)."""
    c = _cfg()
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise WhisperAusente(
            "O faster-whisper não está instalado neste PC: rode o atualizar.bat "
            "(ou: python -m pip install faster-whisper)."
        ) from e
    nome = modelo or c["whisper_modelo"]
    pasta = str(config.expandir(c["whisper_pasta_modelos"])) if c.get("whisper_pasta_modelos") else None
    chave = (nome, c["whisper_dispositivo"], c["whisper_computacao"], pasta)
    if chave in _modelos:
        return _modelos[chave]
    if _precisa_baixar(nome, pasta):
        log.info(
            "Primeira vez com o modelo Whisper '%s': vou baixar da internet (%s), só desta vez. "
            "Pode levar alguns minutos.", nome, _TAMANHOS.get(nome, "tamanho variável"),
        )
    try:
        m = WhisperModel(nome, device=c["whisper_dispositivo"], compute_type=c["whisper_computacao"], download_root=pasta)
    except Exception as e:
        raise ModeloIndisponivel(
            f"Não consegui carregar o modelo Whisper '{nome}' ({e.__class__.__name__}: {e}). "
            "Na primeira vez ele é baixado da internet: confira a conexão e rode de novo."
        ) from e
    _modelos[chave] = m
    return m


def transcrever(caminho: str | Path, modelo: str | None = None) -> list[dict]:
    """Palavras faladas com tempo: ``[{"ini_s", "fim_s", "texto", "prob"}]`` (tempo na linha do tempo do arquivo)."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroTranscricao(f"Arquivo não existe: {caminho}")
    c = _cfg()
    m = carregar_modelo(modelo)
    opcoes = {"language": c["whisper_idioma"], "word_timestamps": True, "vad_filter": True}
    if c.get("whisper_prompt"):
        opcoes["initial_prompt"] = c["whisper_prompt"]
    log.info("Transcrevendo %s (no processador leva mais ou menos o tempo do vídeo)", caminho.name)
    segmentos, _info = m.transcribe(str(caminho), **opcoes)
    palavras: list[dict] = []
    for seg in segmentos:
        for w in getattr(seg, "words", None) or []:
            texto = str(getattr(w, "word", "") or "").strip()
            if not texto or w.start is None:
                continue
            ini = float(w.start)
            fim = max(float(w.end if w.end is not None else ini), ini)
            item = {"ini_s": round(ini, 3), "fim_s": round(fim, 3), "texto": texto}
            prob = getattr(w, "probability", None)
            if prob is not None:
                item["prob"] = round(float(prob), 3)
            palavras.append(item)
    palavras.sort(key=lambda p: p["ini_s"])
    log.info("%s: %d palavra(s)", caminho.name, len(palavras))
    return palavras


# ---------------------------------------------------------------- blocos de legenda

def _sem_bordas(texto: str) -> str:
    return texto.strip(_BORDAS)


def _fecha_frase(texto: str) -> bool:
    return texto.rstrip(_FECHA_ASPAS).endswith(FINAL)


def _tem_virgula(texto: str) -> bool:
    return texto.rstrip(_FECHA_ASPAS).endswith(VIRGULA)


def _nao_fecha(texto: str, lista: set[str]) -> bool:
    """Artigo, preposição, "R$"…: não pode ser a última palavra de um bloco (nem de uma linha)."""
    if _fecha_frase(texto) or _tem_virgula(texto):
        return False
    return _sem_bordas(texto).lower() in lista or texto.lower() in lista


def _titulo(texto: str) -> bool:
    s = _sem_bordas(texto)
    return len(s) >= 2 and s[0].isupper() and any(ch.islower() for ch in s[1:])


class _Regras:
    def __init__(self, c: dict):
        self.max_palavras = max(1, int(c["legenda_max_palavras"]))
        self.max_c = int(c["legenda_max_caracteres_linha"])
        self.max_linhas = int(c["legenda_max_linhas"])
        self.max_cps = float(c["legenda_max_cps"])
        self.min_s = float(c["legenda_min_s"])
        self.pausa_s = float(c["legenda_pausa_s"])
        self.virgula = bool(c["legenda_quebra_virgula"])
        self.emendar_s = float(c.get("legenda_emendar_s") or 0.0)
        self.nao_fecham = {str(p).lower() for p in c["palavras_que_nao_fecham_bloco"]}

    def linhas(self, textos: list[str]) -> list[str] | None:
        """Até 2 linhas equilibradas dentro do limite; ``None`` se não couber. Palavra sozinha sempre cabe."""
        inteira = " ".join(textos)
        if len(inteira) <= self.max_c or len(textos) == 1:
            return [inteira]
        if self.max_linhas < 2:
            return None
        melhor: tuple[float, list[str]] | None = None
        for k in range(1, len(textos)):
            l1, l2 = " ".join(textos[:k]), " ".join(textos[k:])
            if len(l1) > self.max_c or len(l2) > self.max_c:
                continue
            custo = max(len(l1), len(l2)) + (50 if _nao_fecha(textos[k - 1], self.nao_fecham) else 0)
            if melhor is None or custo < melhor[0]:
                melhor = (custo, [l1, l2])
        return melhor[1] if melhor else None


def _preco_loja(texto: str) -> str:
    """Preço no formato da loja, com a mesma regra do plano (§5): "R$230" → "R$230,00", "R$229.99" → "R$229,99"."""
    if "R$" not in texto:
        return texto
    from .plano import _normalizar_precos  # import tardio: o plano importa este módulo

    return _normalizar_precos(texto)


def _limpar(palavras: list[dict]) -> list[list]:
    """Ordena, descarta vazios e garante tempos crescentes (o Whisper às vezes repete ou inverte)."""
    itens = []
    for p in palavras:
        texto = str(p.get("texto", "")).strip()
        if not texto or p.get("ini_s") is None:
            continue
        ini = float(p["ini_s"])
        fim = float(p["fim_s"]) if p.get("fim_s") is not None else ini
        itens.append((ini, fim, texto))
    itens.sort(key=lambda x: x[0])
    saida: list[list] = []
    for ini, fim, texto in itens:
        if saida and saida[-1][2] == "R$" and texto[:1].isdigit():
            # preço no formato da loja, cifrão colado (§5): "R$" + "229,99" → "R$229,99"
            saida[-1][1], saida[-1][2] = max(fim, saida[-1][1]), _preco_loja("R$" + texto)
            continue
        texto = _preco_loja(texto)
        if saida:
            ini = max(ini, saida[-1][0] + 0.01)
        saida.append([ini, max(fim, ini + 0.01), texto])
    return saida


def blocos_legenda(palavras: list[dict]) -> list[dict]:
    """Agrupa palavras em blocos de legenda ``[{"ini_s", "fim_s", "texto"}]`` (duas linhas separadas por ``\\n``)."""
    r = _Regras(_cfg())
    ps = _limpar(palavras)
    n = len(ps)
    if not n:
        return []
    textos = [p[2] for p in ps]

    def inicio_frase(j: int) -> bool:
        return j == 0 or _fecha_frase(textos[j - 1])

    def preso(j: int) -> bool:
        """A palavra ``j`` tem que ficar no mesmo bloco da seguinte."""
        if j + 1 >= n:
            return False
        if _nao_fecha(textos[j], r.nao_fecham):
            return True
        # nome e sobrenome ("Maria Ferreira"): duas palavras com inicial maiúscula fora do início de frase
        return (_titulo(textos[j]) and _titulo(textos[j + 1]) and not inicio_frase(j)
                and not _tem_virgula(textos[j]) and not _fecha_frase(textos[j]))

    # 1) frases: quebra obrigatória em pausa longa ou pontuação final (nunca depois de palavra presa)
    frases: list[list[int]] = [[0]]
    for i in range(1, n):
        pausa = ps[i][0] - ps[i - 1][1] > r.pausa_s
        if (pausa or _fecha_frase(textos[i - 1])) and not preso(i - 1):
            frases.append([i])
        else:
            frases[-1].append(i)

    # 2) cada frase em blocos equilibrados (programação dinâmica)
    def dividir(idx: list[int]) -> list[list[int]]:
        m = len(idx)
        ideal = m / math.ceil(m / r.max_palavras)
        custo_ate = [math.inf] * (m + 1)
        origem = [0] * (m + 1)
        custo_ate[0] = 0.0
        for j in range(1, m + 1):
            for s in range(1, r.max_palavras + 1):
                i = j - s
                if i < 0:
                    break
                if custo_ate[i] == math.inf:
                    continue
                linhas = r.linhas([textos[k] for k in idx[i:j]])
                if linhas is None:
                    continue
                custo = 2.0 + 0.1 * (s - ideal) ** 2
                if s == 1 and m > 1:
                    custo += 4.0
                if len(linhas) > 1:
                    custo += 1.0
                if j < m:
                    ultima = idx[j - 1]
                    if preso(ultima):
                        custo += 100.0
                    elif r.virgula and _tem_virgula(textos[ultima]):
                        custo -= 2.5
                if custo_ate[i] + custo < custo_ate[j]:
                    custo_ate[j] = custo_ate[i] + custo
                    origem[j] = i
        partes, j = [], m
        while j > 0:
            partes.append(idx[origem[j]:j])
            j = origem[j]
        return partes[::-1]

    grupos = [b for frase in frases for b in dividir(frase)]

    # 3) tempos: mínimo na tela e ≤ cps máximo, estendendo o fim sem invadir o próximo bloco
    blocos: list[dict] = []
    for k, g in enumerate(grupos):
        linhas = r.linhas([textos[i] for i in g]) or [" ".join(textos[i] for i in g)]
        caracteres = len(" ".join(linhas))
        ini = ps[g[0]][0]
        alvo = max(ps[g[-1]][1], ini + max(r.min_s, caracteres / r.max_cps))
        if k + 1 < len(grupos):
            limite = ps[grupos[k + 1][0]][0]
            fim = min(alvo, limite)
            if limite - fim < r.emendar_s:
                fim = limite  # evita a legenda piscar num intervalo curto
        else:
            fim = alvo
        blocos.append({"ini_s": round(ini, 3), "fim_s": round(max(fim, ini + 0.01), 3), "texto": "\n".join(linhas)})
    return blocos


def conferir_blocos(blocos: list[dict]) -> list[str]:
    """Pontos fora das regras da §5 (fala rápida demais, linha longa, sobreposição). Lista vazia = tudo certo."""
    r = _Regras(_cfg())
    problemas = []
    for i, b in enumerate(blocos):
        texto = str(b.get("texto", ""))
        linhas = texto.split("\n")
        dur = float(b["fim_s"]) - float(b["ini_s"])
        caracteres = len(" ".join(linhas))
        nome = f"bloco {i + 1} ({' '.join(linhas)!r})"
        if dur <= 0:
            problemas.append(f"{nome}: duração zero")
            continue
        if len(linhas) > r.max_linhas:
            problemas.append(f"{nome}: {len(linhas)} linhas (máx. {r.max_linhas})")
        for linha in linhas:
            if len(linha) > r.max_c and " " in linha:
                problemas.append(f"{nome}: linha com {len(linha)} caracteres (máx. {r.max_c})")
        if len(texto.split()) > r.max_palavras:
            problemas.append(f"{nome}: {len(texto.split())} palavras (máx. {r.max_palavras})")
        if caracteres / dur > r.max_cps + 0.05:
            problemas.append(f"{nome}: {caracteres / dur:.0f} caracteres/s (máx. {r.max_cps:g}): fala rápida, encurtar o texto")
        if i + 1 < len(blocos) and float(b["fim_s"]) > float(blocos[i + 1]["ini_s"]) + 1e-6:
            problemas.append(f"{nome}: invade o bloco seguinte")
    return problemas


# ---------------------------------------------------------------- SRT

def _tempo_srt(s: float) -> str:
    ms = max(0, int(round(float(s) * 1000)))
    h, resto = divmod(ms, 3_600_000)
    m, resto = divmod(resto, 60_000)
    seg, ms = divmod(resto, 1000)
    return f"{h:02d}:{m:02d}:{seg:02d},{ms:03d}"


def gerar_srt(blocos: list[dict]) -> str:
    """Texto SRT padrão (``HH:MM:SS,mmm``). Gravar em UTF-8."""
    partes = []
    n = 0
    for b in blocos:
        texto = "\n".join(l.strip() for l in str(b.get("texto", "")).strip().splitlines() if l.strip())
        if not texto:
            continue
        n += 1
        partes.append(f"{n}\n{_tempo_srt(b['ini_s'])} --> {_tempo_srt(b['fim_s'])}\n{texto}\n")
    return "\n".join(partes)


_TEMPOS = re.compile(
    r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)


def _segundos(h: str, m: str, s: str, ms: str) -> float:
    return round(int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000, 3)


def ler_srt(texto: str) -> list[dict]:
    """Lê um SRT (com ou sem BOM, CRLF ou LF) → ``[{"ini_s", "fim_s", "texto"}]``."""
    texto = texto.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    blocos = []
    for parte in re.split(r"\n\s*\n", texto.strip()):
        linhas = parte.split("\n")
        pos = next((i for i, l in enumerate(linhas) if _TEMPOS.search(l)), None)
        if pos is None:
            continue
        g = _TEMPOS.search(linhas[pos]).groups()
        corpo = "\n".join(l.strip() for l in linhas[pos + 1:] if l.strip())
        blocos.append({"ini_s": _segundos(*g[:4]), "fim_s": _segundos(*g[4:]), "texto": corpo})
    return blocos
