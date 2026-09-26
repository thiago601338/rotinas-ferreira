"""Recriar foto de várias cores sem a(s) cor(es) sem estoque, pela API de imagens da OpenAI (ChatGPT).

Regra do usuário (26/09/2026): "quando tiver um carrossel com várias cores e uma delas não tiver, o correto é antes de
tudo pedir pro ChatGPT recriar a imagem tirando aquela cor". Automático pela API (escolha do usuário).

- Só foto (vídeo não dá para recriar: continua cortado). A original nunca é alterada: a recriada é um arquivo NOVO em
  ``Rotinas Ferreira\\stories\\<data>\\recriadas\\``, com uma folha "original | recriada" para a IA conferir.
- ``recriadas.json`` (na mesma pasta) guarda cada recriação; o ``stories.montar`` só usa a imagem de uma mídia que a IA
  aprovou (``"recriadas": ["A - 2"]``) e cujo registro tira todas as cores que estão sem estoque.
- Chave ``OPENAI_API_KEY`` só no ``.env`` do PC; nunca em log (``registro.ocultar``).
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .. import config, midia, registro

log = registro.obter("stories.recriar")

VARIAVEL = "OPENAI_API_KEY"
REGISTRO = "recriadas.json"


class ErroRecriar(RuntimeError):
    """Problema ao recriar (mensagem em português, sem segredo)."""


def _cfg() -> dict:
    return config.carregar("stories")["recriar_imagem"]


def pasta_recriadas(data: str) -> Path:
    return config.pastas().trabalho_stories / data / "recriadas"


def ler_registro(data: str) -> dict:
    caminho = pasta_recriadas(data) / REGISTRO
    if not caminho.is_file():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_registro(data: str, dados: dict) -> None:
    caminho = pasta_recriadas(data) / REGISTRO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho)


def texto_prompt(tirar: list[str], ficam: list[str]) -> str:
    return _cfg()["prompt"].format(tirar=", ".join(tirar), ficam=", ".join(ficam))


def _mensagem_erro(r) -> str:
    try:
        corpo = r.json()
        msg = (corpo.get("error") or {}).get("message") if isinstance(corpo, dict) else None
    except ValueError:
        msg = None
    return registro.ocultar(str(msg or getattr(r, "text", "") or ""))[:300]


def chamar_api(original: Path, prompt: str, http=None) -> bytes:
    """Manda a foto e o pedido para ``images/edits`` e devolve os bytes da imagem nova."""
    chave = (config.segredo(VARIAVEL) or "").strip()
    if not chave:
        raise ErroRecriar(f"Falta {VARIAVEL} no .env ({config.caminho_env()}): a recriação de imagem usa a API da "
                          "OpenAI. Crie a chave em platform.openai.com (API keys) e cole no .env.")
    if http is None:
        import requests as http  # noqa: N813
    c = _cfg()
    tipo = "image/png" if original.suffix.lower() == ".png" else "image/jpeg"
    dados = {"model": c["modelo"], "prompt": prompt, "n": "1"}
    for campo in ("size", "quality"):
        if c.get(campo):
            dados[campo] = str(c[campo])
    try:
        with open(original, "rb") as f:
            r = http.post(c["url"], headers={"Authorization": f"Bearer {chave}"},
                          files={"image": (original.name, f, tipo)}, data=dados, timeout=float(c.get("timeout_s", 240)))
    except Exception as e:  # noqa: BLE001 - rede: tipo e mensagem limpa
        raise ErroRecriar(f"Sem resposta da OpenAI ({e.__class__.__name__}): {registro.ocultar(str(e))[:200]}") from e
    if r.status_code != 200:
        if r.status_code == 401:
            raise ErroRecriar(f"A OpenAI recusou a chave: confira {VARIAVEL} no .env.")
        raise ErroRecriar(f"A OpenAI recusou o pedido (HTTP {r.status_code}): {_mensagem_erro(r)}")
    try:
        b64 = r.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ErroRecriar("A OpenAI respondeu sem a imagem (formato inesperado).") from e


def _arquivo_novo(pasta: Path, base: str, ext: str) -> Path:
    destino = pasta / f"{base}{ext}"
    n = 2
    while destino.exists():  # nunca sobrescreve uma recriação anterior
        destino = pasta / f"{base} ({n}){ext}"
        n += 1
    return destino


def _salvar_jpeg(dados: bytes, destino: Path) -> None:
    from PIL import Image

    with Image.open(io.BytesIO(dados)) as img:
        img.convert("RGB").save(destino, "JPEG", quality=int(_cfg().get("qualidade_jpeg", 95)))


def _folha(original: Path, recriada: Path, destino: Path, rotulo: str) -> None:
    """Original | recriada lado a lado, para a IA conferir se só a cor pedida saiu."""
    from PIL import Image, ImageDraw

    alt = 900
    partes = []
    for p in (original, recriada):
        with Image.open(p) as img:
            img = img.convert("RGB")
            partes.append(img.resize((max(1, round(img.width * alt / img.height)), alt)))
    folha = Image.new("RGB", (sum(p.width for p in partes) + 30, alt + 50), "white")
    x = 10
    for p, titulo in zip(partes, ("ORIGINAL", "RECRIADA")):
        folha.paste(p, (x, 45))
        ImageDraw.Draw(folha).text((x, 12), titulo, fill=(0, 0, 0))
        x += p.width + 10
    ImageDraw.Draw(folha).text((200, 12), rotulo, fill=(160, 0, 0))
    folha.save(destino, "JPEG", quality=85)


def _midia_do_manifesto(manifesto: dict, nome: str) -> dict:
    m = re.match(r"^([A-Z]{1,2}) - \d+$", nome)
    letra = (manifesto.get("letras") or {}).get(m.group(1)) if m else None
    for item in (letra or {}).get("midias") or []:
        if item.get("nome") == nome:
            return item
    raise ErroRecriar(f"{nome}: não está no manifesto do dia (nome no formato 'A - 2').")


def recriar(data: str, midias: list[dict], http=None) -> dict:
    """``midias``: ``[{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde", "Rosa"]}]`` (cores do cadastro)."""
    from . import pedido  # pedido usa este módulo; importar aqui evita o ciclo

    data = pedido._validar_data(data)
    manifesto = pedido.carregar_manifesto(data)
    pasta = pasta_recriadas(data)
    pasta.mkdir(parents=True, exist_ok=True)
    reg = ler_registro(data)
    feitas = []
    for pedido_midia in midias or []:
        nome = str(pedido_midia.get("nome") or "").strip()
        tirar = [str(c).strip() for c in pedido_midia.get("tirar") or [] if str(c).strip()]
        ficam = [str(c).strip() for c in pedido_midia.get("ficam") or [] if str(c).strip()]
        if not tirar or not ficam:
            raise ErroRecriar(f"{nome or '(sem nome)'}: informe 'tirar' (cores sem estoque) e 'ficam' (cores com estoque).")
        item = _midia_do_manifesto(manifesto, nome)
        if item.get("tipo") != "foto":
            raise ErroRecriar(f"{nome}: só foto pode ser recriada (é {item.get('tipo')}); vídeo continua cortado.")
        original = Path(item.get("caminho") or "")
        if not original.is_file():
            raise ErroRecriar(f"{nome}: arquivo original não encontrado ({original}).")
        prompt = texto_prompt(tirar, ficam)
        log.info("Recriando %s sem %s (ficam %s)", nome, ", ".join(tirar), ", ".join(ficam))
        imagem = chamar_api(original, prompt, http=http)
        destino = _arquivo_novo(pasta, f"{nome} sem {' e '.join(tirar)}", ".jpg")
        _salvar_jpeg(imagem, destino)
        folha = destino.with_name(destino.stem + " - folha.jpg")
        _folha(original, destino, folha, f"{nome}: sem {', '.join(tirar)}")
        reg[nome] = {"arquivo": destino.name, "caminho": str(destino), "hash": midia.hash_arquivo(destino),
                     "tirar": tirar, "ficam": ficam, "original": str(original), "hash_original": item.get("hash"),
                     "folha": str(folha), "prompt": prompt, "modelo": _cfg()["modelo"],
                     "criado_em": datetime.now().astimezone().isoformat(timespec="seconds")}
        _gravar_registro(data, reg)
        feitas.append({"nome": nome, "recriada": str(destino), "folha": str(folha), "tirar": tirar, "ficam": ficam})
    return {"data": data, "recriadas": feitas, "pasta": str(pasta),
            "proximo_passo": "Conferir cada folha (só a cor pedida saiu; peça, modelo, fundo e textos iguais). Aprovada → "
                             "stories.montar com \"recriadas\": [nomes]. Ruim → recriar de novo ou pôr em \"excluir\"."}


def aprovada(data: str, nome: str, sem_estoque: list[str]) -> dict | None:
    """Registro da recriação de ``nome`` se ela tira todas as cores ``sem_estoque`` e o arquivo continua igual."""
    reg = ler_registro(data).get(nome)
    if not reg:
        return None
    tiradas = {c.casefold() for c in reg.get("tirar") or []}
    if not {c.casefold() for c in sem_estoque} <= tiradas:
        return None
    caminho = Path(reg.get("caminho") or "")
    if not caminho.is_file() or midia.hash_arquivo(caminho) != reg.get("hash"):
        return None
    return reg


# ---------------------------------------------------------------- fila e terminal

def tarefa(args: dict, ctx) -> dict:
    """Pedido ``stories.recriar``: ``{"data", "midias": [{"nome", "tirar": [...], "ficam": [...]}]}``."""
    if not args.get("data") or not args.get("midias"):
        raise ErroRecriar('Informe "data" e "midias" ([{"nome", "tirar", "ficam"}]).')
    res = recriar(args["data"], args["midias"])
    ctx.arquivo("recriar.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas stories-recriar",
                                description="Recria uma foto de várias cores sem as cores sem estoque (API da OpenAI).")
    p.add_argument("--data", required=True)
    p.add_argument("--midia", required=True, help='nome da mídia, ex.: "A - 2"')
    p.add_argument("--tirar", required=True, help="cores sem estoque, separadas por vírgula")
    p.add_argument("--ficam", required=True, help="cores com estoque que ficam, separadas por vírgula")
    a = p.parse_args(argv)
    try:
        res = recriar(a.data, [{"nome": a.midia, "tirar": a.tirar.split(","), "ficam": a.ficam.split(",")}])
    except Exception as e:  # noqa: BLE001 - mensagem clara no terminal
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    for f in res["recriadas"]:
        print(f"{f['nome']}: {f['recriada']}\n  folha: {f['folha']}")
    return 0
