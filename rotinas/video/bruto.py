"""B1: prepara o bruto de um vídeo (inventário, tomadas, silêncios, fala, batidas e folhas de contato).

Lê ``videos/bruto/<projeto>/`` e grava tudo em ``videos/trabalho/<projeto>/``. Nunca escreve na pasta do bruto:
qualquer conversão (ex.: cópia em fps constante) vira arquivo novo em ``trabalho/``.
"""

from __future__ import annotations

import argparse
import importlib
import itertools
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .. import config, ferramentas, folha, midia, registro
from . import transcricao

log = registro.obter("video.bruto")

# Usados só se faltar a chave em config/video.json (a config manda).
PADRAO = {
    "subpastas_video": {"bruto": "bruto", "trabalho": "trabalho", "exportado": "exportado",
                        "musicas": "musicas", "folhas": "folhas", "cfr": "cfr"},
    "bruto_extensoes_video": [".mp4", ".mov", ".m4v", ".3gp", ".mkv", ".avi", ".webm"],
    "bruto_extensoes_audio": [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"],
    "bruto_ignorar": ["desktop.ini", "thumbs.db", ".ds_store", "*.aae", "*.tmp", "*.parcial.*"],
    "tomadas_limiar_cena": 0.30,
    "tomadas_min_s": 0.6,
    "tomadas_escala_largura": 320,
    "silencio_ruido_db": -35,
    "silencio_min_s": 0.3,
    "audio_silencioso_db": -50.0,
    "largura_minima": 1080,
    "fps_cintilacao": [25, 50, 100],
    "fps_cintilacao_tolerancia": 0.5,
    "vfr_fps_alvo": 30,
    "vfr_crf": 18,
    "ffmpeg_timeout_s": 3600,
    "folha_quadros_por_tomada": 3,
    "folha_margem_quadro_s": 0.2,
    "folha_tomadas_por_folha": 12,
    "folha_colunas": 3,
    "folha_altura_quadro": 400,
    "batidas_confianca_min": 0.3,
}

_PROIBIDOS_NOME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# o ffmpeg escreve tempos com "%.6g": perto de zero sai notação científica ("2.08333e-05")
_NUM = r"(-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
_contador_quadros = itertools.count(1)


class ErroBruto(RuntimeError):
    """Problema na preparação do bruto (projeto, pasta ou música)."""


def _cfg() -> dict:
    try:
        dados = config.carregar("video")
    except config.ErroConfig:
        dados = {}
    return {**PADRAO, **dados}


# ---------------------------------------------------------------- pastas

def _subpastas() -> dict:
    return {**PADRAO["subpastas_video"], **(_cfg().get("subpastas_video") or {})}


def _validar_projeto(projeto: str) -> str:
    nome = str(projeto or "").strip()
    if not nome or nome in (".", "..") or _PROIBIDOS_NOME.search(nome) or nome.endswith("."):
        raise ErroBruto(f"Nome de projeto inválido: {projeto!r}. Use o nome da pasta em videos\\bruto (sem barras).")
    return nome


def pastas_projeto(projeto: str) -> dict[str, Path]:
    """Pastas do projeto: ``bruto`` (só leitura), ``trabalho``, ``folhas`` e ``exportado``."""
    nome = _validar_projeto(projeto)
    base = config.pastas().videos
    sub = _subpastas()
    trabalho = base / sub["trabalho"] / nome
    return {
        "bruto": base / sub["bruto"] / nome,
        "trabalho": trabalho,
        "folhas": trabalho / sub["folhas"],
        "exportado": base / sub["exportado"],
    }


def pasta_musicas() -> Path:
    return config.pastas().videos / _subpastas()["musicas"]


def _dentro(filho: Path, pai: Path) -> bool:
    try:
        filho.resolve().relative_to(pai.resolve())
        return True
    except ValueError:
        return False


def _conferir_separacao(p: dict[str, Path]) -> None:
    for chave in ("trabalho", "folhas"):
        if _dentro(p[chave], p["bruto"]):
            raise ErroBruto(f"A pasta de {chave} ({p[chave]}) está dentro do bruto. Corrija config/video.json.")


def _chave_natural(caminho: Path) -> list:
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", caminho.name)]


def _ignorar(caminho: Path, padroes: list[str]) -> bool:
    nome = caminho.name.lower()
    if nome.startswith((".", "~$")):
        return True
    return any(Path(nome).match(p.lower()) if "*" in p else nome == p.lower() for p in padroes)


def _listar(pasta: Path) -> tuple[list[Path], list[str]]:
    """(vídeos e áudios em ordem natural de nome, nomes de itens que ficaram de fora)."""
    c = _cfg()
    exts = {e.lower() for e in c["bruto_extensoes_video"]} | {e.lower() for e in c["bruto_extensoes_audio"]}
    midias, fora = [], []
    for item in sorted(pasta.iterdir(), key=_chave_natural):
        if _ignorar(item, c["bruto_ignorar"]):
            continue
        if item.is_file() and item.suffix.lower() in exts:
            midias.append(item)
        else:
            fora.append(item.name + ("\\" if item.is_dir() else ""))
    return midias, fora


# ---------------------------------------------------------------- inventário

def _situacao_audio(caminho: Path, info: midia.InfoMidia) -> str:
    if not info.tem_audio:
        return "sem_audio"
    pico = midia.volume_maximo_db(caminho)
    if pico is None or pico <= float(_cfg()["audio_silencioso_db"]):
        return "silencioso"
    return "com_audio"


def _fps_txt(fps: float) -> str:
    return f"{fps:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def avisos_midia(info: midia.InfoMidia, audio: str | None = None) -> list[str]:
    """Avisos acionáveis do guia §2 (captação) para um arquivo do bruto."""
    c = _cfg()
    av: list[str] = []
    if info.tipo == "video":
        if info.hdr:
            av.append(f"HDR ligado ({info.transferencia or 'HDR'}): desligar HDR na câmera (\"Vídeo HDR\" no iPhone, "
                      "\"HDR10+\" no Samsung); projeto e exportação em SDR Rec.709. Este clipe fica lavado no projeto "
                      "SDR: baixar realces/exposição e exportar um teste.")
        if info.fps_variavel:
            av.append(f"taxa de quadros variável (média {_fps_txt(info.fps or 0)} fps; áudio pode escorregar): converter "
                      f"para {c['vfr_fps_alvo']} fps constante (HandBrake Constant Framerate, RF 18–20) antes de importar, "
                      "ou rodar de novo com --normalizar-vfr (cópia em trabalho\\, o bruto fica intacto).")
        tol = float(c["fps_cintilacao_tolerancia"])
        # com fps variável a média não é a taxa escolhida na câmera (30 fps no escuro cai para ~25 de média)
        if info.fps and not info.fps_variavel and any(abs(info.fps - float(f)) <= tol for f in c["fps_cintilacao"]):
            av.append(f"gravado a {_fps_txt(info.fps)} fps: risco de cintilação (faixas) sob lâmpada de 60 Hz. Gravar a 30 "
                      "ou 60 fps; se aparecerem faixas, obturador 1/60 (30 fps) ou 1/120 (60 fps).")
        if info.largura and info.altura:
            if info.largura > info.altura:
                av.append(f"vídeo horizontal ({info.largura}×{info.altura}): no projeto 9:16 usar Vídeo > Básico > Tela "
                          "(fundo desfocado) ou Escala ≈316%, ou Reenquadramento automático (Pro). Gravar na vertical 9:16.")
            menor = min(info.largura, info.altura)
            if menor < int(c["largura_minima"]):
                av.append(f"resolução {info.largura}×{info.altura}: lado menor de {menor} px, abaixo de "
                          f"{c['largura_minima']}; perde nitidez no 1080×1920 e não aguenta punch-in/zoom. "
                          "Gravar em 4K a 30 fps.")
        if not info.tem_audio:
            av.append("sem faixa de áudio: se era para ter fala, gravar de novo com o microfone ligado; "
                      "se o vídeo vai só com música, pode seguir.")
    if audio == "silencioso":
        av.append("áudio em silêncio: se era para ter fala, conferir o microfone/lapela; se vai só com música, pode seguir.")
    if Path(info.caminho).suffix.lower() == ".mov":
        av.append(".mov do iPhone abre direto no CapCut (não precisa converter); só o arquivo final precisa ser .mp4 "
                  "para a galeria do Instagram no BlueStacks, e a exportação já sai em .mp4.")
    return av


def _inventariar(caminho: Path) -> dict:
    try:
        info = midia.sondar(caminho)
        audio = _situacao_audio(caminho, info)
    except (midia.ErroMidia, ferramentas.ErroComando, ValueError) as e:
        log.warning("Não consegui ler %s: %s", caminho.name, e)
        return {"arquivo": caminho.name, "caminho": str(caminho), "tipo": None, "erro": str(e),
                "avisos": [f"não consegui ler o arquivo ({e}). Copiar de novo do celular sem compressão "
                           "(cabo, Google Drive ou Quick Share; nunca pelo WhatsApp)."]}
    d = info.como_dict()
    d.update({"arquivo": caminho.name, "audio": audio, "avisos": avisos_midia(info, audio)})
    return d


def inventario(projeto: str) -> list[dict]:
    """Vídeos e áudios do bruto: dados do ffprobe (``InfoMidia``) + ``arquivo``, ``audio`` e ``avisos``."""
    pasta = pastas_projeto(projeto)["bruto"]
    if not pasta.is_dir():
        raise ErroBruto(f"Não achei a pasta do bruto: {pasta}. Copie os vídeos do projeto para lá.")
    midias, _ = _listar(pasta)
    return [_inventariar(m) for m in midias]


# ---------------------------------------------------------------- tomadas e silêncios

def _trechos(cortes: list[float], duracao: float, min_s: float) -> list[tuple[float, float]]:
    """Trechos entre cortes cobrindo ``[0, duracao]``; trecho menor que ``min_s`` é juntado ao vizinho."""
    if duracao <= 0:
        return []
    mantidos = [0.0]
    for t in sorted(cortes):
        if 0.0 < t < duracao and t - mantidos[-1] >= min_s:
            mantidos.append(t)
    if len(mantidos) > 1 and duracao - mantidos[-1] < min_s:
        mantidos.pop()
    mantidos.append(duracao)
    return list(zip(mantidos, mantidos[1:]))


def detectar_tomadas(caminho: str | Path, limiar: float | None = None, min_s: float | None = None) -> list[dict]:
    """Tomadas por troca de cena (ffmpeg ``select='gt(scene,X)',showinfo``): ``[{"ini_s", "fim_s"}]``, cobrindo o arquivo todo."""
    c = _cfg()
    limiar = float(c["tomadas_limiar_cena"] if limiar is None else limiar)
    min_s = float(c["tomadas_min_s"] if min_s is None else min_s)
    caminho = Path(caminho)
    duracao = midia.sondar(caminho).duracao_s or 0.0
    filtros = [f"scale={int(c['tomadas_escala_largura'])}:-2"] if c.get("tomadas_escala_largura") else []
    filtros += [f"select='gt(scene,{limiar})'", "showinfo"]
    r = ferramentas.rodar(
        [midia.ffmpeg(), "-hide_banner", "-nostdin", "-nostats", "-i", str(caminho), "-map", "0:v:0", "-an",
         "-vf", ",".join(filtros), "-f", "null", "-"],
        timeout=float(c["ffmpeg_timeout_s"]),
    )
    cortes = sorted({float(m) for m in re.findall(r"pts_time:\s*" + _NUM, r.stderr or "")})
    return [{"ini_s": round(a, 3), "fim_s": round(b, 3)} for a, b in _trechos(cortes, duracao, min_s)]


def detectar_silencios(caminho: str | Path, ruido_db: float | None = None, min_s: float | None = None) -> list[dict]:
    """Trechos em silêncio (ffmpeg ``silencedetect``): ``[{"ini_s", "fim_s"}]``. Sem faixa de áudio = tudo silêncio."""
    c = _cfg()
    ruido_db = float(c["silencio_ruido_db"] if ruido_db is None else ruido_db)
    min_s = float(c["silencio_min_s"] if min_s is None else min_s)
    caminho = Path(caminho)
    info = midia.sondar(caminho)
    duracao = info.duracao_s or 0.0
    if not info.tem_audio:
        return [{"ini_s": 0.0, "fim_s": round(duracao, 3)}] if duracao else []
    r = ferramentas.rodar(
        [midia.ffmpeg(), "-hide_banner", "-nostdin", "-nostats", "-i", str(caminho), "-map", "0:a:0", "-vn",
         "-af", f"silencedetect=noise={ruido_db}dB:d={min_s}", "-f", "null", "-"],
        timeout=float(c["ffmpeg_timeout_s"]),
    )
    silencios, inicio = [], None
    for tipo, valor in re.findall(r"silence_(start|end):\s*" + _NUM, r.stderr or ""):
        t = min(max(float(valor), 0.0), duracao or float(valor))
        if tipo == "start":
            inicio = t
        else:
            if t > (inicio or 0.0):
                silencios.append({"ini_s": round(inicio or 0.0, 3), "fim_s": round(t, 3)})
            inicio = None
    if inicio is not None and duracao - inicio > 0:
        silencios.append({"ini_s": round(inicio, 3), "fim_s": round(duracao, 3)})
    return silencios


# ---------------------------------------------------------------- cópia em fps constante

def _assinatura_origem(caminho: Path) -> dict:
    """O que identifica a versão do original de onde a cópia saiu (nome, tamanho e data de modificação)."""
    st = caminho.stat()
    return {"arquivo": caminho.name, "tamanho": st.st_size, "mtime_ns": st.st_mtime_ns}


def _copia_cfr(caminho: Path, trabalho: Path) -> Path:
    """Cópia em fps constante (H.264 CRF da config + AAC 48 kHz) em ``trabalho/cfr``. O original não é tocado.

    O nome da cópia leva a extensão do original (``IMG_0001.MOV`` e ``IMG_0001.mp4`` no mesmo bruto não dividem
    a cópia) e, ao lado, ``<cópia>.origem.json`` guarda nome, tamanho e data de modificação do original: a cópia
    só é reaproveitada se o original for o mesmo; se ele foi trocado, a cópia (arquivo nosso) é gerada de novo.
    """
    c = _cfg()
    alvo = int(c["vfr_fps_alvo"])
    ext = caminho.suffix.lstrip(".").lower() or "sem-ext"
    destino = trabalho / _subpastas()["cfr"] / f"{caminho.stem}-{ext}-cfr{alvo}.mp4"
    marca = destino.with_name(destino.stem + ".origem.json")
    origem = _assinatura_origem(caminho)
    if destino.exists():
        try:
            anterior = json.loads(marca.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            anterior = None
        if anterior == origem:
            log.info("Cópia em fps constante já existe: %s", destino.name)
            return destino
        log.info("O original de %s mudou (ou a cópia não tem registro de origem): gerando de novo", destino.name)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.stem + ".parcial.mp4")
    if parcial.exists():
        parcial.unlink()  # sobra nossa de uma tentativa anterior
    log.info("Gerando cópia de %s em %d fps constante (pode levar alguns minutos)", caminho.name, alvo)
    ferramentas.rodar(
        [midia.ffmpeg(), "-hide_banner", "-nostdin", "-i", str(caminho), "-map", "0:v:0", "-map", "0:a:0?",
         "-map_metadata", "0", "-vf", f"fps={alvo},format=yuv420p", "-c:v", "libx264", "-preset", "slow",
         "-crf", str(c["vfr_crf"]), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
         str(parcial)],
        timeout=float(c["ffmpeg_timeout_s"]),
    )
    os.replace(parcial, destino)  # por cima de uma cópia nossa antiga; o bruto continua intacto
    marca.write_text(json.dumps(origem, ensure_ascii=False), encoding="utf-8")
    return destino


# ---------------------------------------------------------------- folhas de contato

def tempo_curto(s: float) -> str:
    """``64.2`` → ``"1:04,2"`` (décimo de segundo, vírgula decimal)."""
    decimos = int(round(max(s, 0.0) * 10))
    seg, d = divmod(decimos, 10)
    m, seg = divmod(seg, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{seg:02d},{d}" if h else f"{m}:{seg:02d},{d}"


def _tempos_quadros(ini: float, fim: float, n: int, margem: float) -> list[float]:
    """``n`` instantes: início + margem, meio(s) e fim − margem (margem menor em tomada curta)."""
    if n <= 1:
        return [(ini + fim) / 2]
    m = min(margem, (fim - ini) / 4)
    a, b = ini + m, fim - m
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def _quadro(caminho: Path, t: float, pasta_tmp: Path, largura: int, altura: int):
    from PIL import Image, ImageDraw

    erro: Exception | None = None
    for tempo in (t, max(t - 0.5, 0.0)):  # o contêiner às vezes dura mais que a imagem
        destino = pasta_tmp / f"q{next(_contador_quadros):06d}.jpg"
        try:
            midia.extrair_quadro(caminho, tempo, destino, largura=largura)
            with Image.open(destino) as img:
                return img.convert("RGB")
        except (midia.ErroMidia, ferramentas.ErroComando, OSError) as e:
            erro = e
    log.warning("Sem quadro em %.2f s de %s: %s", t, caminho.name, erro)
    img = Image.new("RGB", (largura, altura), (70, 70, 70))
    ImageDraw.Draw(img).text((10, 10), "sem quadro", fill=(255, 255, 255))
    return img


def _rotulo_tomada(tomada: dict, largura_max: int) -> tuple[str, int]:
    """Rótulo ``T03 · IMG_0001 · 0:04,2–0:06,0`` com fonte grande; nome comprido é encurtado antes de a fonte diminuir."""
    nome = Path(tomada["arquivo"]).stem
    tempos = f"{tempo_curto(tomada['ini_s'])}–{tempo_curto(tomada['fim_s'])}"

    def cabe(texto: str, tamanho: int) -> bool:
        return folha.fonte(tamanho).getlength(texto) + 2 * max(4, tamanho // 6) <= largura_max

    for tamanho in (28, 26, 24):
        if cabe(f"{tomada['id']} · {nome} · {tempos}", tamanho):
            return f"{tomada['id']} · {nome} · {tempos}", tamanho
    for tamanho in (24, 20, 16):
        curto = nome
        while len(curto) > 6 and not cabe(f"{tomada['id']} · {curto}… · {tempos}", tamanho):
            curto = curto[:-1]
        if cabe(f"{tomada['id']} · {curto}… · {tempos}", tamanho):
            break
    return f"{tomada['id']} · {curto}… · {tempos}", tamanho


def _montar_folha(itens: list[tuple], destino: Path, titulo: str, colunas: int, celula: tuple[int, int]) -> Path:
    """Grade de tiras (uma por tomada) com o rótulo numa faixa acima de cada tira, sem cobrir os quadros."""
    from PIL import Image, ImageDraw

    larg, alt = celula
    faixa, espaco, topo = 46, 10, 58
    colunas = max(1, min(colunas, len(itens)))
    linhas = math.ceil(len(itens) / colunas)
    img = Image.new("RGB", (colunas * (larg + espaco) + espaco, topo + linhas * (faixa + alt + espaco) + espaco), (255, 255, 255))
    desenho = ImageDraw.Draw(img)
    desenho.text((espaco, 14), titulo, font=folha.fonte(30), fill=(0, 0, 0))
    for n, (tira, tomada) in enumerate(itens):
        x = espaco + (n % colunas) * (larg + espaco)
        y = topo + (n // colunas) * (faixa + alt + espaco)
        tira = tira.copy()
        tira.thumbnail((larg, alt))
        caixa = Image.new("RGB", (larg, alt), (24, 24, 24))
        caixa.paste(tira, ((larg - tira.width) // 2, (alt - tira.height) // 2))
        img.paste(caixa, (x, y + faixa))
        texto, tamanho = _rotulo_tomada(tomada, larg)
        folha.rotulo(desenho, (x + max(4, tamanho // 6), y + (faixa - tamanho) // 2 - 2), texto, tamanho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, "JPEG", quality=85)
    return destino


def _gerar_folhas(projeto: str, arquivos: list[dict], tomadas: list[dict], pasta_folhas: Path) -> list[str]:
    """Folhas ``tomadas-01.jpg…`` (≈12 tomadas por folha, 3 quadros por tomada). Devolve caminhos relativos ao trabalho."""
    c = _cfg()
    por_folha = max(1, int(c["folha_tomadas_por_folha"]))
    altura = int(c["folha_altura_quadro"])
    n_quadros = max(1, int(c["folha_quadros_por_tomada"]))
    celula = (n_quadros * round(altura * 9 / 16) + (n_quadros - 1) * 4, altura)
    sub = _subpastas()["folhas"]
    pasta_folhas.mkdir(parents=True, exist_ok=True)
    for velha in pasta_folhas.glob("tomadas-*.jpg"):
        velha.unlink()  # folhas geradas por nós numa rodada anterior
    por_nome = {a["arquivo"]: a for a in arquivos}
    paginas = [tomadas[i:i + por_folha] for i in range(0, len(tomadas), por_folha)]
    relativos = []
    with tempfile.TemporaryDirectory(prefix="rotinas-quadros-") as tmp:
        pasta_tmp = Path(tmp)
        for n, pagina in enumerate(paginas, 1):
            itens = []
            for t in pagina:
                arq = por_nome[t["arquivo"]]
                info = arq["info"] or {}
                w, h = info.get("largura") or 9, info.get("altura") or 16
                larg_q = max(2, int(round(altura * w / h / 2)) * 2)
                fonte = Path(arq["caminho_edicao"])
                quadros = [_quadro(fonte, s, pasta_tmp, larg_q, altura)
                           for s in _tempos_quadros(t["ini_s"], t["fim_s"], n_quadros, float(c["folha_margem_quadro_s"]))]
                itens.append((folha.tira(quadros, altura=altura), t))
            nome = f"tomadas-{n:02d}.jpg"
            titulo = f"{projeto} · tomadas {pagina[0]['id']}–{pagina[-1]['id']} · folha {n}/{len(paginas)}"
            _montar_folha(itens, pasta_folhas / nome, titulo, int(c["folha_colunas"]), celula)
            rel = f"{sub}/{nome}"
            for t in pagina:
                t["folha"] = rel
            relativos.append(rel)
            log.info("Folha de contato %s (%d tomada(s))", nome, len(pagina))
    return relativos


# ---------------------------------------------------------------- transcrição

def _gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def _transcrever(arquivos: list[dict], trabalho: Path, avisos: list[str]) -> dict | None:
    """Transcreve os arquivos com fala → ``legendas.srt`` (ou ``legendas-<arquivo>.srt``) + ``transcricao.json``."""
    com_fala = [a for a in arquivos if a["fala"]]
    if not com_fala:
        return None
    feitos = []
    for a in com_fala:
        try:
            palavras = transcricao.transcrever(a["caminho"])
        except transcricao.ModeloIndisponivel as e:
            avisos.append(f"{e} Segui sem transcrição (legendas pelo CapCut: Legendas > Legendas automáticas).")
            return None
        except Exception as e:  # noqa: BLE001 - um arquivo com problema não derruba a preparação
            log.warning("Transcrição de %s falhou: %s", a["arquivo"], e)
            avisos.append(f"{a['arquivo']}: a transcrição falhou ({e.__class__.__name__}: {e}); segui sem ela.")
            continue
        a["fala"] = bool(palavras)
        if palavras:
            feitos.append((a, palavras))
    if not feitos:
        avisos.append("Nenhuma fala reconhecida nos arquivos com áudio.")
        return None
    c = _cfg()
    varios = len(feitos) > 1
    registro_json = {"gerado_em": _agora(), "modelo": c.get("whisper_modelo"), "idioma": c.get("whisper_idioma"), "arquivos": []}
    todas, srts = [], {}
    for a, palavras in feitos:
        blocos = transcricao.blocos_legenda(palavras)
        nome_srt = f"legendas-{Path(a['arquivo']).stem}.srt" if varios else "legendas.srt"
        if nome_srt.casefold() in {s.casefold() for s in srts.values()}:
            # IMG_0001.MOV e IMG_0001.mp4 no mesmo bruto: um .srt não pode apagar o outro
            nome_srt = f"legendas-{Path(a['arquivo']).name.replace('.', '-')}.srt"
        (trabalho / nome_srt).write_text(transcricao.gerar_srt(blocos), encoding="utf-8")
        srts[a["arquivo"]] = nome_srt
        problemas = transcricao.conferir_blocos(blocos)
        if problemas:
            avisos.append(f"{nome_srt}: {len(problemas)} bloco(s) para revisar no CapCut (ex.: {problemas[0]}).")
        registro_json["arquivos"].append({"arquivo": a["arquivo"], "caminho": a["caminho"], "srt": nome_srt,
                                          "palavras": palavras, "blocos": blocos})
        todas += [{"arquivo": a["arquivo"], **p} for p in palavras]
        log.info("Legendas: %s (%d palavra(s), %d bloco(s))", nome_srt, len(palavras), len(blocos))
    _gravar_json(trabalho / "transcricao.json", registro_json)
    return {"arquivo_srt": None if varios else srts[feitos[0][0]["arquivo"]], "arquivos_srt": srts, "palavras": todas}


# ---------------------------------------------------------------- música

def _resolver_musica(musica: str, p: dict[str, Path]) -> Path:
    c = Path(str(musica).strip().strip('"'))
    candidatos = [c] if c.is_absolute() else [p["bruto"] / c, pasta_musicas() / c]
    for x in candidatos:
        if x.is_file():
            return x
    raise ErroBruto(f"Música não encontrada: {musica}. Procurei em: " + "; ".join(str(x) for x in candidatos))


def _batidas(caminho: Path, trabalho: Path, avisos: list[str]) -> dict | None:
    try:
        batidas = importlib.import_module(f"{__package__}.batidas")
        r = batidas.detectar_batidas(caminho)
    except Exception as e:  # noqa: BLE001 - sem batidas a preparação continua
        log.warning("Batidas de %s: %s", caminho.name, e)
        avisos.append(f"Não consegui marcar as batidas de {caminho.name} ({e.__class__.__name__}: {e}); segui sem "
                      "batidas (marcar no CapCut: M no ritmo).")
        return None
    dados = {"arquivo": str(caminho), **r}
    _gravar_json(trabalho / "batidas.json", dados)
    confianca = r.get("confianca")
    if not r.get("batidas_s"):
        avisos.append(f"Não achei batidas regulares em {caminho.name}; segui sem batidas (marcar no CapCut: M no "
                      "ritmo, ou usar outra faixa-guia de batida marcada).")
    elif confianca is not None and float(confianca) < float(_cfg()["batidas_confianca_min"]):
        avisos.append(f"Batidas de {caminho.name} com confiança baixa ({float(confianca):.2f}): conferir o BPM "
                      f"({r.get('bpm')}) e as marcas no CapCut antes de cortar na batida.")
    log.info("Música %s: %s BPM, %d batida(s)", caminho.name, r.get("bpm"), len(r.get("batidas_s") or []))
    return dados


# ---------------------------------------------------------------- preparar

def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _mesmo_arquivo(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return a.resolve() == b.resolve()


def _analisar(item: dict, trabalho: Path, normalizar_vfr: bool) -> dict:
    caminho = Path(item["caminho"])
    avisos = list(item.get("avisos") or [])
    base = {"arquivo": item["arquivo"], "caminho": str(caminho), "caminho_edicao": str(caminho)}
    if item.get("tipo") is None:
        return {**base, "info": None, "avisos": avisos, "audio": None, "tomadas": [], "silencios": [],
                "fala": False, "erro": item.get("erro")}
    info = {k: v for k, v in item.items() if k not in ("arquivo", "audio", "avisos")}
    edicao = caminho
    if normalizar_vfr and info.get("tipo") == "video" and info.get("fps_variavel"):
        try:
            edicao = _copia_cfr(caminho, trabalho)
            avisos.append(f"cópia em fps constante gerada: {edicao} (importar esta no CapCut).")
        except (ferramentas.ErroComando, OSError) as e:
            avisos.append(f"não consegui gerar a cópia em fps constante ({e}); converter no HandBrake.")
    tomadas: list[dict] = []
    if info.get("tipo") == "video":
        try:
            tomadas = detectar_tomadas(edicao)
        except ferramentas.ErroComando as e:
            avisos.append(f"detecção de tomadas falhou ({e}); o arquivo inteiro virou uma tomada.")
            dur = info.get("duracao_s") or 0.0
            tomadas = [{"ini_s": 0.0, "fim_s": round(dur, 3)}] if dur else []
    try:
        silencios = detectar_silencios(caminho)
    except ferramentas.ErroComando as e:
        avisos.append(f"detecção de silêncios falhou ({e}).")
        silencios = []
    log.info("%s: %d tomada(s), %d silêncio(s), áudio %s", caminho.name, len(tomadas), len(silencios), item.get("audio"))
    return {**base, "caminho_edicao": str(edicao), "info": info, "avisos": avisos, "audio": item.get("audio"),
            "tomadas": tomadas, "silencios": silencios, "fala": item.get("audio") == "com_audio"}


def preparar(projeto: str, musica: str | None = None, transcrever: bool = True, normalizar_vfr: bool = False) -> dict:
    """Prepara o bruto do projeto e grava ``trabalho/<projeto>/bruto.json`` (formato em interfaces do Entregável B)."""
    p = pastas_projeto(projeto)
    projeto = p["bruto"].name
    if not p["bruto"].is_dir():
        raise ErroBruto(f"Não achei a pasta do bruto: {p['bruto']}. Copie os vídeos do projeto para lá.")
    _conferir_separacao(p)
    caminho_musica = _resolver_musica(musica, p) if musica else None
    midias, fora = _listar(p["bruto"])
    if caminho_musica:
        midias = [m for m in midias if not _mesmo_arquivo(m, caminho_musica)]
    if not midias:
        raise ErroBruto(f"Nenhum vídeo ou áudio em {p['bruto']}.")
    trabalho = p["trabalho"]
    trabalho.mkdir(parents=True, exist_ok=True)
    avisos: list[str] = []
    if fora:
        avisos.append(f"Ficaram de fora (não são vídeo nem áudio, ou são subpastas): {', '.join(fora)}.")
    log.info("Preparando o bruto de %s: %d arquivo(s)", projeto, len(midias))

    arquivos = [_analisar(_inventariar(m), trabalho, normalizar_vfr) for m in midias]
    tomadas: list[dict] = []
    for a in arquivos:
        for t in a["tomadas"]:
            t_id = f"T{len(tomadas) + 1:02d}"
            a_t = {"id": t_id, "ini_s": t["ini_s"], "fim_s": t["fim_s"]}
            t.clear()
            t.update(a_t)
            tomadas.append({**a_t, "arquivo": a["arquivo"], "dur_s": round(a_t["fim_s"] - a_t["ini_s"], 3), "folha": None})
    folhas = _gerar_folhas(projeto, arquivos, tomadas, p["folhas"]) if tomadas else []
    dados_transcricao = _transcrever(arquivos, trabalho, avisos) if transcrever else None
    dados_musica = _batidas(caminho_musica, trabalho, avisos) if caminho_musica else None

    resultado = {
        "projeto": projeto,
        "gerado_em": _agora(),
        "arquivos": arquivos,
        "tomadas": tomadas,
        "transcricao": dados_transcricao,
        "musica": dados_musica,
        "folhas": folhas,
        "avisos": avisos,
    }
    _gravar_json(trabalho / "bruto.json", resultado)
    log.info("bruto.json gravado em %s (%d tomada(s), %d folha(s))", trabalho, len(tomadas), len(folhas))
    return resultado


# ---------------------------------------------------------------- fila e terminal

def resumo(r: dict) -> dict:
    """Resumo curto para o resultado da fila (o detalhe fica no bruto.json)."""
    trabalho = pastas_projeto(r["projeto"])["trabalho"]
    transc = r.get("transcricao") or {}
    musica = r.get("musica")
    return {
        "projeto": r["projeto"],
        "trabalho": str(trabalho),
        "bruto_json": str(trabalho / "bruto.json"),
        "arquivos": [{"arquivo": a["arquivo"], "tomadas": len(a["tomadas"]), "fala": a["fala"], "avisos": a["avisos"]}
                     for a in r["arquivos"]],
        "tomadas": len(r["tomadas"]),
        "folhas": [str(trabalho / f) for f in r["folhas"]],
        "legendas": [str(trabalho / s) for s in (transc.get("arquivos_srt") or {}).values()],
        "palavras": len(transc.get("palavras") or []),
        "musica": {k: musica.get(k) for k in ("arquivo", "bpm", "confianca")} if musica else None,
        "avisos": r["avisos"],
    }


def tarefa(args: dict, ctx) -> dict:
    """Pedido ``video.preparar``: ``{"projeto", "musica"?, "transcrever"?, "normalizar_vfr"?}``."""
    projeto = args.get("projeto")
    if not projeto:
        raise ValueError("Falta o argumento 'projeto' (nome da pasta em videos\\bruto).")
    r = preparar(projeto, musica=args.get("musica"), transcrever=bool(args.get("transcrever", True)),
                 normalizar_vfr=bool(args.get("normalizar_vfr", False)))
    return resumo(r)


def texto_resumo(r: dict) -> str:
    s = resumo(r)
    linhas = [f"Projeto {s['projeto']}: {len(s['arquivos'])} arquivo(s), {s['tomadas']} tomada(s), "
              f"{len(s['folhas'])} folha(s) de contato.", f"Trabalho: {s['trabalho']}"]
    linhas += [f"  {Path(f).name}" for f in s["folhas"]]
    if s["legendas"]:
        linhas.append(f"Legendas: {', '.join(Path(x).name for x in s['legendas'])} ({s['palavras']} palavra(s))")
    if s["musica"]:
        bpm, confianca = s["musica"].get("bpm"), s["musica"].get("confianca")
        linhas.append(f"Música: {Path(s['musica']['arquivo']).name}, "
                      + (f"{float(bpm):.1f} BPM".replace(".", ",") if bpm else "BPM não detectado")
                      + (f" (confiança {float(confianca):.2f})".replace(".", ",") if confianca is not None else ""))
    avisos = [f"{a['arquivo']}: {x}" for a in s["arquivos"] for x in a["avisos"]] + s["avisos"]
    if avisos:
        linhas.append("Avisos:")
        linhas += [f"  - {x}" for x in avisos]
    return "\n".join(linhas)


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m rotinas video-preparar",
        description="B1: inventário, tomadas, silêncios, transcrição, batidas e folhas de contato do bruto.",
    )
    ap.add_argument("--projeto", required=True, help="nome da pasta em videos\\bruto")
    ap.add_argument("--musica", help="faixa-guia: caminho completo, ou nome do arquivo em bruto\\<projeto> ou videos\\musicas")
    ap.add_argument("--sem-transcricao", action="store_true", help="não transcreve a fala")
    ap.add_argument("--normalizar-vfr", action="store_true",
                    help="gera cópia em fps constante (em trabalho\\) dos vídeos com taxa de quadros variável")
    a = ap.parse_args(argv)
    try:
        r = preparar(a.projeto, musica=a.musica, transcrever=not a.sem_transcricao, normalizar_vfr=a.normalizar_vfr)
    except (ErroBruto, midia.ErroMidia, ferramentas.FerramentaAusente, ferramentas.ErroComando) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    print(texto_resumo(r))
    return 0
