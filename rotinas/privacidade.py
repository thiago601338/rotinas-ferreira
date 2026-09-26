"""Privacidade das telas salvas (print ``.png`` + XML do uiautomator) antes de irem para o GitHub.

O repositório é público e ``execucoes/`` vai inteiro para lá. Em 25/09/2026 um teste salvou uma conversa do Direct
com uma cliente e a notificação flutuante do Android com o nome, a foto e a mensagem dela. Regras:

- Tela do Direct (conversa ou caixa de entrada): o par ``.xml``/``.png`` não vai para o git.
- Notificação do Android (pacote ``com.android.systemui``): texto e descrição apagados no XML; a faixa da notificação
  flutuante (nós ``android:id/...``) é coberta de preto no print. Os ícones da barra de status só têm descrição
  ("Notificação do Instagram: <nome>"), que também é apagada.

Tudo configurável em ``config/diagnostico.json`` → ``execucao.privacidade``.
"""

from __future__ import annotations

import re
from pathlib import Path

MARCA = "[oculto]"
RE_NO = re.compile(r"<node\b[^>]*>")
RE_LIMITES = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _attr(tag: str, nome: str) -> str:
    m = re.search(rf'\s{re.escape(nome)}="([^"]*)"', tag)
    return m.group(1) if m else ""


def _trocar_attr(tag: str, nome: str, valor: str) -> str:
    return re.sub(rf'(\s{re.escape(nome)}=)"[^"]*"', lambda m: f'{m.group(1)}"{valor}"', tag, count=1)


def _limites(tag: str) -> tuple[int, int, int, int] | None:
    m = RE_LIMITES.fullmatch(_attr(tag, "bounds"))
    return tuple(int(v) for v in m.groups()) if m else None  # type: ignore[return-value]


def tela_privada(xml: str, marcadores: list[str]) -> str | None:
    """O marcador de tela privada (ex.: ``:id/direct_thread``) achado nos ``resource-id``, ou ``None``."""
    for tag in RE_NO.findall(xml):
        rid = _attr(tag, "resource-id")
        for m in marcadores:
            if m and m in rid:
                return m
    return None


def limpar_xml(xml: str, pacote: str, ids_mantidos: list[str]) -> tuple[str, int, tuple[int, int] | None, int | None]:
    """Apaga texto e descrição dos nós do ``pacote`` (notificações do Android).

    Devolve ``(xml_limpo, nós_apagados, faixa_y_da_notificação_flutuante, largura_da_tela)``. A faixa vem dos nós
    ``android:id/...`` do pacote (modelo de notificação: nome, mensagem, ações), ou ``None`` se não há flutuante.
    """
    apagados = 0
    ys: list[int] = []
    largura = None

    def trocar(m: re.Match) -> str:
        nonlocal apagados, largura
        tag = m.group(0)
        lim = _limites(tag)
        if largura is None and lim and lim[0] == 0 and lim[1] == 0:
            largura = lim[2]  # primeiro nó que começa em (0, 0): a tela inteira
        if _attr(tag, "package") != pacote or _attr(tag, "resource-id") in ids_mantidos:
            return tag
        novo = tag
        for nome in ("text", "content-desc"):
            if _attr(novo, nome) not in ("", MARCA):
                novo = _trocar_attr(novo, nome, MARCA)
        if novo != tag:
            apagados += 1
        if _attr(tag, "resource-id").startswith("android:id/") and lim:
            ys.extend((lim[1], lim[3]))
        return novo

    limpo = RE_NO.sub(trocar, xml)
    faixa = (min(ys), max(ys)) if ys else None
    return limpo, apagados, faixa, largura


def cobrir_print(png: Path, faixa: tuple[int, int], largura_tela: int | None, margem: tuple[int, int]) -> None:
    """Pinta de preto, na largura toda, a faixa ``(y0, y1)`` da tela (com margem acima/abaixo)."""
    from PIL import Image, ImageDraw

    with Image.open(png) as img:
        img.load()
        escala = img.width / largura_tela if largura_tela else 1.0
        y0 = max(0, int((faixa[0] - margem[0]) * escala))
        y1 = min(img.height, int((faixa[1] + margem[1]) * escala))
        img = img.convert("RGB")
        ImageDraw.Draw(img).rectangle([0, y0, img.width, y1], fill=(0, 0, 0))
        img.save(png, "PNG")


def conferir_par(xml_path: Path, cfg: dict) -> dict:
    """Confere um ``.xml`` salvo de tela (e o ``.png`` de mesmo nome). Não apaga nada: diz se é tela privada e, se
    não for, limpa o XML e cobre o print no lugar. ``{"privada": marcador|None, "apagados": n, "coberto": bool}``."""
    xml_path = Path(xml_path)
    xml = xml_path.read_text(encoding="utf-8", errors="surrogateescape")
    marcador = tela_privada(xml, list(cfg.get("marcadores_tela_privada") or []))
    if marcador:
        return {"privada": marcador, "apagados": 0, "coberto": False}
    limpo, apagados, faixa, largura = limpar_xml(xml, cfg.get("pacote_notificacoes", "com.android.systemui"),
                                                 list(cfg.get("ids_mantidos") or []))
    if limpo != xml:
        xml_path.write_text(limpo, encoding="utf-8", errors="surrogateescape")
    coberto = False
    png = xml_path.with_suffix(".png")
    if faixa and png.is_file():
        margem = cfg.get("margem_print_px") or [56, 24]
        cobrir_print(png, faixa, largura, (int(margem[0]), int(margem[1])))
        coberto = True
    return {"privada": None, "apagados": apagados, "coberto": coberto}


def _texto_permitido(valor: str, permitidos: list[str]) -> bool:
    """Só o termo exato da interface (sem nome de pessoa junto: "Enviar para fulana" some). Exceção: com "Facebook",
    basta conter (a opção de compartilhar no Facebook, que o script precisa achar e desligar)."""
    v = " ".join(valor.lower().split())
    return any(v == p.lower() for p in permitidos) or ("facebook" in v and len(v) <= 80 and "@" not in v)


def anonimizar_tela(xml_path: Path, permitidos: list[str]) -> dict:
    """Para telas fora do fluxo conhecido (``testar.bat tela``), que podem listar pessoas (ex.: "Enviar para" na
    tela de compartilhar): apaga todo texto/descrição que não seja um termo da interface em ``permitidos`` e cobre de
    preto, no print, a área de cada nó apagado. ``resource-id`` e classe ficam (são o que os seletores usam)."""
    xml_path = Path(xml_path)
    xml = xml_path.read_text(encoding="utf-8", errors="surrogateescape")
    caixas: list[tuple[int, int, int, int]] = []
    largura = altura = None

    def trocar(m: re.Match) -> str:
        nonlocal largura, altura
        tag = m.group(0)
        lim = _limites(tag)
        if largura is None and lim and lim[0] == 0 and lim[1] == 0:
            largura, altura = lim[2], lim[3]
        novo = tag
        for nome in ("text", "content-desc"):
            valor = _attr(novo, nome)
            if valor and valor != MARCA and not _texto_permitido(valor, permitidos):
                novo = _trocar_attr(novo, nome, MARCA)
        if novo != tag and lim:
            caixas.append(lim)
        return novo

    limpo = RE_NO.sub(trocar, xml)
    xml_path.write_text(limpo, encoding="utf-8", errors="surrogateescape")
    png = xml_path.with_suffix(".png")
    cobertos = 0
    if caixas and png.is_file():
        from PIL import Image, ImageDraw

        with Image.open(png) as img:
            img.load()
            img = img.convert("RGB")
        escala = img.width / largura if largura else 1.0
        area_tela = (largura or img.width) * (altura or img.height)
        desenho = ImageDraw.Draw(img)
        for x0, y0, x1, y1 in caixas:
            if (x1 - x0) * (y1 - y0) > 0.4 * area_tela:
                continue  # contêiner da tela inteira: cobrir apagaria o print todo
            desenho.rectangle([int(x0 * escala), int(y0 * escala), int(x1 * escala), int(y1 * escala)], fill=(0, 0, 0))
            cobertos += 1
        img.save(png, "PNG")
    return {"apagados": len(caixas), "cobertos": cobertos}
