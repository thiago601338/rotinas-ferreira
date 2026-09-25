"""Mídia sintética para os testes (ffmpeg + Pillow)."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def video(
    caminho: Path,
    duracao: float = 2.0,
    audio: str | None = "tom",
    largura: int = 360,
    altura: int = 640,
    fps: int = 30,
    codec: str = "libx264",
    cor: str = "green",
    criado_em: datetime | None = None,
    cenas: list[str] | None = None,
    volume_db: float = -12.0,
) -> Path:
    """Vídeo de teste. ``audio``: "tom", "silencio", "fala" (tom intermitente) ou None (sem faixa).

    ``cenas``: lista de cores; divide a duração em cortes secos (para testar detecção de tomadas).
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    entradas: list[str] = []
    if cenas:
        parte = duracao / len(cenas)
        filtros = []
        for i, c in enumerate(cenas):
            entradas += ["-f", "lavfi", "-i", f"color=c={c}:s={largura}x{altura}:r={fps}:d={parte:.3f}"]
            filtros.append(f"[{i}:v]")
        filtro_v = "".join(filtros) + f"concat=n={len(cenas)}:v=1:a=0[v]"
        n_v = len(cenas)
    else:
        entradas += ["-f", "lavfi", "-i", f"testsrc2=s={largura}x{altura}:r={fps}:d={duracao}"]
        filtro_v = "[0:v]null[v]"
        n_v = 1
    mapa_a: list[str] = []
    if audio == "tom":
        entradas += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duracao}"]
        filtro_a = f";[{n_v}:a]volume={volume_db}dB[a]"
        mapa_a = ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    elif audio == "silencio":
        entradas += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duracao}"]
        filtro_a = f";[{n_v}:a]anull[a]"
        mapa_a = ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    elif audio == "fala":
        # 0,5 s de tom, 0,5 s de silêncio, alternando
        entradas += ["-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={duracao}"]
        filtro_a = f";[{n_v}:a]volume='if(lt(mod(t,1),0.5),1,0)':eval=frame,volume={volume_db}dB[a]"
        mapa_a = ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    else:
        filtro_a = ""
    meta = ["-metadata", f"creation_time={criado_em.strftime('%Y-%m-%dT%H:%M:%S.000000Z')}"] if criado_em else []
    codec_args = ["-c:v", codec, "-pix_fmt", "yuv420p"]
    if codec == "libx264":
        codec_args += ["-preset", "ultrafast"]
    if codec == "libx265":
        codec_args += ["-preset", "ultrafast", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
    _ff(*entradas, "-filter_complex", filtro_v + filtro_a, "-map", "[v]", *mapa_a, *codec_args, *meta, "-t", str(duracao), str(caminho))
    return caminho


def foto(caminho: Path, cor=(200, 30, 30), tamanho=(600, 800), tirada_em: datetime | None = None, texto: str | None = None) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", tamanho, cor)
    if texto:
        from PIL import ImageDraw

        ImageDraw.Draw(img).text((20, 20), texto, fill=(255, 255, 255))
    exif = Image.Exif()
    if tirada_em:
        exif.get_ifd(0x8769)[36867] = tirada_em.strftime("%Y:%m:%d %H:%M:%S")
        exif[306] = tirada_em.strftime("%Y:%m:%d %H:%M:%S")
    fmt = "PNG" if caminho.suffix.lower() == ".png" else "JPEG"
    img.save(caminho, fmt, exif=exif.tobytes() if tirada_em else b"")
    return caminho


def musica_cliques(caminho: Path, bpm: float = 120.0, duracao: float = 10.0, inicio: float = 0.0) -> Path:
    """Faixa com cliques exatos no tempo (para testar batidas)."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    periodo = 60.0 / bpm
    expr = f"if(lt(mod(t-{inicio}+10*{periodo},{periodo}),0.02)*gte(t,{inicio}),sin(2*PI*1000*t),0)"
    _ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={duracao}", "-c:a", "pcm_s16le", str(caminho))
    return caminho
