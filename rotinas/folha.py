"""Folha de contato: várias imagens numa grade, cada uma com um rótulo grande."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

_FONTES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def fonte(tamanho: int) -> ImageFont.ImageFont:
    for f in _FONTES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, tamanho)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:  # Pillow antigo
        return ImageFont.load_default()


def _encaixar(img: Image.Image, largura: int, altura: int, fundo=(24, 24, 24)) -> Image.Image:
    """Redimensiona mantendo a proporção e centraliza num quadro fixo."""
    img = img.convert("RGB")
    img.thumbnail((largura, altura), Image.LANCZOS)
    quadro = Image.new("RGB", (largura, altura), fundo)
    quadro.paste(img, ((largura - img.width) // 2, (altura - img.height) // 2))
    return quadro


def rotulo(desenho: ImageDraw.ImageDraw, xy: tuple[int, int], texto: str, tamanho: int) -> None:
    f = fonte(tamanho)
    x, y = xy
    caixa = desenho.textbbox((x, y), texto, font=f)
    margem = max(4, tamanho // 6)
    desenho.rectangle((caixa[0] - margem, caixa[1] - margem, caixa[2] + margem, caixa[3] + margem), fill=(0, 0, 0))
    desenho.text((x, y), texto, font=f, fill=(255, 235, 59))


def montar(
    itens: Iterable[tuple[Image.Image | str | Path, str]],
    destino: Path,
    titulo: str | None = None,
    colunas: int | None = None,
    celula: tuple[int, int] = (270, 480),
    qualidade: int = 85,
) -> Path:
    """Monta a folha e grava em ``destino`` (JPEG). ``itens`` = (imagem ou caminho, rótulo)."""
    itens = list(itens)
    if not itens:
        raise ValueError("Folha de contato sem itens")
    n = len(itens)
    colunas = colunas or min(n, 6 if n > 4 else n)
    linhas = math.ceil(n / colunas)
    larg, alt = celula
    espaco = 8
    topo = 56 if titulo else 0
    folha = Image.new("RGB", (colunas * (larg + espaco) + espaco, topo + linhas * (alt + espaco) + espaco), (255, 255, 255))
    desenho = ImageDraw.Draw(folha)
    if titulo:
        desenho.text((espaco, 12), titulo, font=fonte(30), fill=(0, 0, 0))
    for i, (img, texto) in enumerate(itens):
        if not isinstance(img, Image.Image):
            from .midia import abrir_imagem

            img = abrir_imagem(Path(img))
        quadro = _encaixar(img, larg, alt)
        x = espaco + (i % colunas) * (larg + espaco)
        y = topo + espaco + (i // colunas) * (alt + espaco)
        folha.paste(quadro, (x, y))
        rotulo(desenho, (x + 8, y + 8), texto, max(22, larg // 7))
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    folha.save(destino, "JPEG", quality=qualidade)
    return destino


def tira(imagens: list[Image.Image], altura: int = 480, espaco: int = 4) -> Image.Image:
    """Junta vários quadros lado a lado (ex.: início, meio e fim de um vídeo) numa só imagem."""
    redim = []
    for img in imagens:
        img = img.convert("RGB")
        escala = altura / img.height
        redim.append(img.resize((max(1, int(img.width * escala)), altura), Image.LANCZOS))
    largura = sum(i.width for i in redim) + espaco * (len(redim) - 1)
    saida = Image.new("RGB", (largura, altura), (24, 24, 24))
    x = 0
    for img in redim:
        saida.paste(img, (x, 0))
        x += img.width + espaco
    return saida
