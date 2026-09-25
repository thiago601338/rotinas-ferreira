"""Mídia: ffprobe, conversão, áudio, quadros, hash e data de captura.

Regra fixa: nunca sobrescrever nem apagar mídia do usuário. Toda saída é arquivo novo.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config, ferramentas, registro

log = registro.obter("midia")

EXT_FOTO_PADRAO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
EXT_VIDEO_PADRAO = {".mp4", ".mov", ".m4v", ".3gp"}
EXT_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class ErroMidia(RuntimeError):
    """Problema com um arquivo de mídia."""


def _ext_stories(chave: str, padrao: set[str]) -> set[str]:
    try:
        return {e.lower() for e in config.carregar("stories").get(chave, [])} or padrao
    except config.ErroConfig:
        return padrao


def eh_foto(caminho: Path) -> bool:
    return Path(caminho).suffix.lower() in (_ext_stories("extensoes_foto", EXT_FOTO_PADRAO) | {".heif"})


def eh_video(caminho: Path) -> bool:
    return Path(caminho).suffix.lower() in _ext_stories("extensoes_video", EXT_VIDEO_PADRAO)


def eh_audio(caminho: Path) -> bool:
    return Path(caminho).suffix.lower() in EXT_AUDIO


def ffmpeg() -> str:
    return ferramentas.exigir("ffmpeg")


def ffprobe() -> str:
    return ferramentas.exigir("ffprobe")


# ---------------------------------------------------------------- ffprobe

@dataclass
class InfoMidia:
    caminho: str
    tipo: str  # "video", "foto" ou "audio"
    largura: int | None = None  # já considerando a rotação (como aparece na tela)
    altura: int | None = None
    rotacao: int = 0
    duracao_s: float | None = None
    fps: float | None = None
    fps_variavel: bool = False
    codec_video: str | None = None
    pix_fmt: str | None = None
    hdr: bool = False
    transferencia: str | None = None
    tem_audio: bool = False
    codec_audio: str | None = None
    canais: int | None = None
    taxa_amostragem: int | None = None
    bitrate_kbps: float | None = None
    tamanho_bytes: int = 0
    criado_em: str | None = None
    formato: str | None = None
    extras: dict = field(default_factory=dict)

    @property
    def vertical(self) -> bool:
        return bool(self.largura and self.altura and self.altura > self.largura)

    def como_dict(self) -> dict:
        return asdict(self)


def _fracao(texto: str | None) -> float | None:
    if not texto or texto in ("0/0", "N/A"):
        return None
    if "/" in texto:
        a, b = texto.split("/", 1)
        try:
            a_f, b_f = float(a), float(b)
        except ValueError:
            return None
        return a_f / b_f if b_f else None
    try:
        return float(texto)
    except ValueError:
        return None


def _rotacao(stream: dict) -> int:
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(float(tags["rotate"])) % 360
        except ValueError:
            pass
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(round(-float(sd["rotation"]))) % 360
            except (TypeError, ValueError):
                pass
    return 0


def sondar_json(caminho: Path) -> dict:
    r = ferramentas.rodar(
        [ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(caminho)],
        timeout=60,
    )
    return json.loads(r.stdout or "{}")


def sondar(caminho: Path) -> InfoMidia:
    """Informações técnicas de um vídeo, foto ou áudio."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroMidia(f"Arquivo não existe: {caminho}")
    dados = sondar_json(caminho)
    streams = dados.get("streams") or []
    fmt = dados.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if eh_foto(caminho):
        tipo = "foto"
    elif eh_audio(caminho) or (video is None and audio is not None):
        tipo = "audio"
    else:
        tipo = "video"

    info = InfoMidia(caminho=str(caminho), tipo=tipo, tamanho_bytes=caminho.stat().st_size)
    info.formato = fmt.get("format_name")
    dur = _fracao(fmt.get("duration")) or (video and _fracao(video.get("duration"))) or (audio and _fracao(audio.get("duration")))
    info.duracao_s = round(dur, 3) if dur and tipo != "foto" else None
    br = _fracao(fmt.get("bit_rate"))
    info.bitrate_kbps = round(br / 1000, 1) if br else None
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    info.criado_em = tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate")

    if video:
        w, h = video.get("width"), video.get("height")
        info.rotacao = _rotacao(video)
        if info.rotacao in (90, 270) and w and h:
            w, h = h, w
        info.largura, info.altura = w, h
        info.codec_video = video.get("codec_name")
        info.pix_fmt = video.get("pix_fmt")
        if tipo != "foto":
            media = _fracao(video.get("avg_frame_rate"))
            real = _fracao(video.get("r_frame_rate"))
            info.fps = round(media or real or 0, 3) or None
            if media and real and abs(media - real) / real > 0.02:
                info.fps_variavel = True
        trc = video.get("color_transfer")
        info.transferencia = trc
        info.hdr = trc in ("smpte2084", "arib-std-b67") or (video.get("color_primaries") == "bt2020" and trc not in (None, "bt709"))
    if audio:
        info.tem_audio = True
        info.codec_audio = audio.get("codec_name")
        info.canais = audio.get("channels")
        try:
            info.taxa_amostragem = int(audio.get("sample_rate")) if audio.get("sample_rate") else None
        except ValueError:
            info.taxa_amostragem = None
    return info


# ---------------------------------------------------------------- áudio

def volume_maximo_db(caminho: Path) -> float | None:
    """Pico do áudio em dBFS (``volumedetect``). ``None`` se não tem áudio."""
    r = ferramentas.rodar(
        [ffmpeg(), "-hide_banner", "-nostats", "-i", str(caminho), "-vn", "-af", "volumedetect", "-f", "null", "-"],
        timeout=600,
        verificar=False,
    )
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf)\s*dB", r.stderr or "")
    if not m:
        return None
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


def situacao_audio(caminho: Path, limiar_db: float | None = None) -> str:
    """``"sem_audio"``, ``"silencioso"`` ou ``"com_audio"``."""
    if limiar_db is None:
        try:
            limiar_db = float(config.carregar("stories").get("silencio_limiar_db", -50.0))
        except config.ErroConfig:
            limiar_db = -50.0
    info = sondar(caminho)
    if not info.tem_audio:
        return "sem_audio"
    pico = volume_maximo_db(caminho)
    if pico is None or pico <= limiar_db:
        return "silencioso"
    return "com_audio"


def loudness(caminho: Path) -> dict:
    """Loudness integrado (LUFS), faixa (LU) e pico real (dBTP) pelo filtro ``ebur128``."""
    r = ferramentas.rodar(
        [ffmpeg(), "-hide_banner", "-nostats", "-i", str(caminho), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
        timeout=900,
        verificar=False,
    )
    texto = r.stderr or ""
    resumo = texto[texto.rfind("Summary:"):] if "Summary:" in texto else texto

    def pega(padrao: str) -> float | None:
        m = re.search(padrao, resumo)
        if not m:
            return None
        v = m.group(1)
        return float("-inf") if v == "-inf" else float(v)

    return {
        "lufs": pega(r"I:\s*(-?[\d.]+|-inf)\s*LUFS"),
        "lra": pega(r"LRA:\s*(-?[\d.]+)\s*LU"),
        "pico_real_dbtp": pega(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS"),
    }


# ---------------------------------------------------------------- conversão

def _garantir_novo(destino: Path) -> None:
    if destino.exists():
        raise ErroMidia(f"Destino já existe, não vou sobrescrever: {destino}")
    destino.parent.mkdir(parents=True, exist_ok=True)


def _tem_filtro(nome: str) -> bool:
    try:
        r = ferramentas.rodar([ffmpeg(), "-hide_banner", "-filters"], timeout=30, verificar=False)
    except ferramentas.FerramentaAusente:
        return False
    return any(linha.split()[1:2] == [nome] for linha in (r.stdout or "").splitlines() if len(linha.split()) > 1)


def converter_para_mp4(origem: Path, destino: Path) -> dict:
    """Converte para ``.mp4`` H.264/AAC num arquivo novo, sem perda visível.

    - H.264 (+ AAC ou sem áudio): só troca o contêiner (sem recompressão).
    - Outros codecs (HEVC do iPhone etc.): H.264 CRF 17, AAC 192 kbps.
    - HDR: converte para SDR Rec.709 com tone mapping, se o ffmpeg tiver ``zscale``.
    """
    origem, destino = Path(origem), Path(destino)
    _garantir_novo(destino)
    info = sondar(origem)
    temporario = destino.with_name(destino.stem + ".parcial" + destino.suffix)
    if temporario.exists():
        temporario.unlink()  # arquivo parcial nosso, de uma tentativa anterior
    copiar_video = info.codec_video == "h264" and not info.hdr and (info.pix_fmt in (None, "yuv420p", "yuvj420p"))
    copiar_audio = (not info.tem_audio) or info.codec_audio == "aac"
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-i", str(origem), "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0"]
    modo = "remux" if (copiar_video and copiar_audio) else "recodificado"
    if copiar_video:
        cmd += ["-c:v", "copy"]
    else:
        filtros = []
        if info.hdr and _tem_filtro("zscale") and _tem_filtro("tonemap"):
            filtros.append(
                "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
            )
            modo += "+hdr_para_sdr"
        elif info.hdr:
            log.warning("Vídeo HDR e o ffmpeg não tem zscale: a cor pode ficar lavada em %s", origem.name)
            filtros.append("format=yuv420p")
        else:
            filtros.append("format=yuv420p")
        cmd += ["-vf", ",".join(filtros), "-c:v", "libx264", "-preset", "slow", "-crf", "17",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if info.tem_audio:
        cmd += ["-c:a", "copy"] if copiar_audio else ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-movflags", "+faststart", str(temporario)]
    ferramentas.rodar(cmd, timeout=3600)
    temporario.replace(destino)
    log.info("Convertido %s → %s (%s)", origem.name, destino.name, modo)
    return {"origem": str(origem), "destino": str(destino), "modo": modo}


def extrair_quadro(caminho: Path, tempo_s: float, destino: Path, largura: int | None = None) -> Path:
    """Salva um quadro do vídeo como imagem (arquivo novo)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-ss", f"{max(tempo_s, 0):.3f}", "-i", str(caminho), "-frames:v", "1"]
    if largura:
        cmd += ["-vf", f"scale={largura}:-2"]
    cmd += ["-q:v", "3", str(destino)]
    ferramentas.rodar(cmd, timeout=120)
    if not destino.exists():
        raise ErroMidia(f"Não consegui extrair quadro em {tempo_s:.2f} s de {Path(caminho).name}")
    return destino


# ---------------------------------------------------------------- identidade e datas

def hash_arquivo(caminho: Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while True:
            parte = f.read(bloco)
            if not parte:
                break
            h.update(parte)
    return h.hexdigest()


def _data_exif(caminho: Path) -> datetime | None:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None
    try:
        with Image.open(caminho) as img:
            exif = img.getexif()
            valor = None
            try:
                valor = exif.get_ifd(0x8769).get(36867)  # DateTimeOriginal
            except Exception:
                valor = None
            valor = valor or exif.get(36867) or exif.get(306)  # DateTime
    except Exception:
        return None
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def data_captura(caminho: Path) -> datetime:
    """Data de captura: EXIF (foto), ``creation_time`` (vídeo) ou data de modificação do arquivo."""
    caminho = Path(caminho)
    if eh_foto(caminho):
        d = _data_exif(caminho)
        if d:
            return d
    elif eh_video(caminho):
        try:
            criado = sondar(caminho).criado_em
        except Exception:
            criado = None
        if criado:
            try:
                d = datetime.fromisoformat(criado.replace("Z", "+00:00"))
                if d.tzinfo:
                    d = d.astimezone().replace(tzinfo=None)
                if d.year > 1971:
                    return d
            except ValueError:
                pass
    return datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc).astimezone().replace(tzinfo=None)


def abrir_imagem(caminho: Path):
    """Abre uma foto com Pillow (inclui HEIC se ``pillow-heif`` estiver instalado), já na orientação do EXIF."""
    from PIL import Image, ImageOps

    if Path(caminho).suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except ImportError as e:
            raise ErroMidia("Foto HEIC: instale o pacote pillow-heif (o instalar.bat faz isso).") from e
    img = Image.open(caminho)
    return ImageOps.exif_transpose(img)
