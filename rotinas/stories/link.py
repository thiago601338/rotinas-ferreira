"""A4: link do WhatsApp da figurinha, texto da figurinha e música dos vídeos sem som.

Regras (``conhecimento/stories.md``):
- Link ``wa.me/<número>?text=<mensagem>``, **sem** ``https://`` (com ``https://`` a figurinha sai sem link).
- A mensagem nomeia a peça daquela letra, nunca um nome genérico.
- Vestido de festa segue ``link_em_vestido_de_festa`` da config; ``null`` = regra não confirmada (perguntar).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote_plus

from .. import config

MSG_FESTA = (
    "Regra não confirmada: vestido de festa leva figurinha de link? Perguntar ao usuário e gravar em "
    "config/stories.json (link_em_vestido_de_festa)"
)
MINUSCULAS_PADRAO = ["de", "da", "do", "das", "dos", "e", "com", "em", "na", "no", "nas", "nos", "para", "sem", "por"]


class ErroRegra(RuntimeError):
    """Regra de stories violada ou não confirmada: a IA não decide sozinha, pergunta ao usuário."""


def _cfg() -> dict:
    return config.carregar("stories")


def normalizar(texto) -> str:
    """Minúsculas, sem acento, espaços simples."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


# ---------------------------------------------------------------- nome da peça e link

def _palavras_minusculas() -> set[str]:
    lista = (_cfg().get("link") or {}).get("palavras_minusculas") or MINUSCULAS_PADRAO
    return {normalizar(p) for p in lista}


def _titulo_palavra(palavra: str) -> str:
    return "-".join(p[:1].upper() + p[1:].lower() for p in palavra.split("-"))


def nome_peca(peca: str) -> str:
    """Nome limpo da peça. Em CAIXA ALTA vira "Título" (preposições minúsculas); senão fica como veio."""
    nome = " ".join(str(peca or "").split())
    if not nome:
        raise ErroRegra("A mensagem do link tem que nomear a peça da letra (nome vazio). Confira a identificação/cadastro.")
    letras = [c for c in nome if c.isalpha()]
    if letras and all(c.isupper() for c in letras):
        minusculas = _palavras_minusculas()
        palavras = nome.split(" ")
        nome = " ".join(
            p.lower() if i and normalizar(p) in minusculas else _titulo_palavra(p) for i, p in enumerate(palavras)
        )
    return nome


def artigo(peca: str) -> str:
    """``artigos.femininas`` → "a"; o resto → ``artigos.padrao`` (pela 1ª palavra, sem acento/maiúscula)."""
    artigos = _cfg().get("artigos") or {}
    primeira = normalizar(peca).split(" ")[0] if normalizar(peca) else ""
    primeira = re.sub(r"^[^\w]+|[^\w]+$", "", primeira)
    femininas = {normalizar(p) for p in artigos.get("femininas") or []}
    return "a" if primeira in femininas else str(artigos.get("padrao") or "o")


def validar_link(url: str) -> str:
    """Recusa link com ``http``/``https`` (a figurinha sairia sem link) ou sem a mensagem."""
    texto = str(url or "").strip()
    if texto.lower().startswith("http") or "://" in texto:
        raise ErroRegra(
            f"Link da figurinha com http/https: {texto}. Tem que ser digitado sem https:// "
            "(com https:// a figurinha aparece mas sai sem link). Corrija link_modelo em config/stories.json."
        )
    if "?text=" not in texto or texto.endswith("?text="):
        raise ErroRegra(f"Link da figurinha sem a mensagem de compra: {texto}")
    return texto


def mensagem(peca: str) -> str:
    """``Quero comprar o Vestido Midi Alça`` (modelo e artigos da config)."""
    nome = nome_peca(peca)
    modelo = _cfg().get("mensagem_modelo") or "Quero comprar {artigo} {peca}"
    return " ".join(modelo.format(artigo=artigo(nome), peca=nome).split())


def montar_link(peca: str) -> str:
    """``wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a`` — nunca com ``http``."""
    c = _cfg()
    numero = re.sub(r"\D", "", str(c.get("whatsapp") or ""))
    if len(numero) < 12:
        raise ErroRegra(f"Número do WhatsApp inválido em config/stories.json (whatsapp): {c.get('whatsapp')!r}")
    modelo = c.get("link_modelo") or "wa.me/{numero}?text={mensagem}"
    return validar_link(modelo.format(numero=numero, mensagem=quote_plus(mensagem(peca))))


# ---------------------------------------------------------------- rodízios

def _rodar(chave: str, indice: int):
    lista = _cfg().get(chave) or []
    if not lista:
        raise ErroRegra(f"config/stories.json sem a lista '{chave}'.")
    return lista[int(indice) % len(lista)]


def texto_figurinha(indice: int) -> str:
    """Texto da figurinha em rodízio (``textos_figurinha``)."""
    return str(_rodar("textos_figurinha", indice))


def musica_para(indice: int) -> dict:
    """Música do Instagram para vídeo sem som, em rodízio (``audios_sem_som``)."""
    return dict(_rodar("audios_sem_som", indice))


# ---------------------------------------------------------------- vestido de festa

def eh_vestido_de_festa(categoria: str | None) -> bool:
    festa = {normalizar(c) for c in _cfg().get("categorias_vestido_de_festa") or []}
    return bool(categoria) and normalizar(categoria) in festa


def leva_link(categoria: str | None) -> bool:
    """A letra leva figurinha de link? Vestido de festa segue a config; ``null`` → ``ErroRegra`` (perguntar)."""
    if not eh_vestido_de_festa(categoria):
        return True
    regra = _cfg().get("link_em_vestido_de_festa")
    if regra is None:
        raise ErroRegra(MSG_FESTA)
    if not isinstance(regra, bool):
        raise ErroRegra(f"link_em_vestido_de_festa em config/stories.json tem que ser true, false ou null (está {regra!r}).")
    return regra


def figurinha(peca: str, indice: int) -> dict:
    """``{"url": ..., "texto": ...}`` para a última mídia da letra."""
    return {"url": montar_link(peca), "texto": texto_figurinha(indice)}
